from __future__ import annotations

import os
import subprocess
from http.client import HTTPException, RemoteDisconnected
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener

from django.core.management.base import BaseCommand

from market_data.models import CompanyProfile


class Command(BaseCommand):
    help = 'Validate CompanyProfile.website values and optionally persist the verified http/https protocol.'

    def add_arguments(self, parser):
        parser.add_argument('--execute', action='store_true', help='Persist verified URLs; default is report-only.')
        parser.add_argument('--timeout', type=float, default=8.0, help='Request timeout in seconds.')
        parser.add_argument('--limit', type=int, default=0, help='Maximum profiles to scan; 0 means all.')
        parser.add_argument('--verbose', action='store_true', help='Show every protocol/method attempt and failure reason.')

    def handle(self, *args, **options):
        if options['timeout'] <= 0:
            self.stderr.write(self.style.ERROR('--timeout must be positive'))
            return
        if options['limit'] < 0:
            self.stderr.write(self.style.ERROR('--limit must not be negative'))
            return

        queryset = CompanyProfile.objects.exclude(website='').select_related('security').order_by('security__ts_code')
        if options['limit']:
            queryset = queryset[:options['limit']]
        opener = build_opener()
        counts = {'scanned': 0, 'skipped': 0, 'valid': 0, 'updated': 0, 'invalid': 0}
        rows = queryset if options['limit'] else queryset.iterator()
        for profile in rows:
            counts['scanned'] += 1
            if profile.protocol.strip().lower() in {'http', 'https'}:
                counts['skipped'] += 1
                if options['verbose']:
                    self.stdout.write(f'SKIP {profile.security.ts_code}: protocol={profile.protocol}')
                continue
            attempts = []
            protocol = self._verify(str(profile.website), opener, options['timeout'], attempts=attempts)
            if options['verbose']:
                for attempt in attempts:
                    self.stdout.write(f"  {attempt['url']} {attempt['method']}: {attempt['result']}")
            if protocol is None:
                counts['invalid'] += 1
                self.stdout.write(f'INVALID {profile.security.ts_code}: {profile.website}')
                continue
            counts['valid'] += 1
            changed = protocol != profile.protocol
            if changed and options['execute']:
                profile.protocol = protocol
                profile.save(update_fields=['protocol', 'synced_at'])
                counts['updated'] += 1
            suffix = ' [updated]' if changed and options['execute'] else (' [would update]' if changed else '')
            display_url = profile.website if '://' in str(profile.website) else f'{protocol}://{profile.website}'
            self.stdout.write(f'OK {profile.security.ts_code}: {display_url}{suffix}')

        mode = 'execute' if options['execute'] else 'report-only'
        self.stdout.write(self.style.SUCCESS(
            f'Website verification complete ({mode}): '
            f"scanned={counts['scanned']} skipped={counts['skipped']} valid={counts['valid']} "
            f"updated={counts['updated']} invalid={counts['invalid']}"
        ))

    @classmethod
    def _verify(cls, raw_value, opener, timeout, *, attempts=None):
        value = raw_value.strip()
        if not value:
            return None
        parsed = urlparse(value if '://' in value else f'https://{value}')
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            return None
        candidates = [value] if '://' in value else [f'https://{value}', f'http://{value}']
        for candidate in candidates:
            verified = cls._request(candidate, opener, timeout, attempts=attempts)
            if verified:
                return urlparse(verified).scheme
        return None

    @staticmethod
    def _request(url, opener, timeout, *, attempts=None):
        headers = {'User-Agent': 'ManNiuNiu-CompanyWebsiteVerifier/1.0'}
        certificate_error = False
        for method, extra_headers in (('HEAD', {}), ('GET', {'Range': 'bytes=0-0'})):
            request = Request(url, headers={**headers, **extra_headers}, method=method)
            try:
                with opener.open(request, timeout=timeout) as response:
                    if 200 <= response.status < 400:
                        final = response.geturl()
                        parsed = urlparse(final)
                        if parsed.scheme in {'http', 'https'} and parsed.netloc:
                            if attempts is not None:
                                attempts.append({'url': url, 'method': method, 'result': f'{response.status} -> {final}'})
                            return final
                    if attempts is not None:
                        attempts.append({'url': url, 'method': method, 'result': f'HTTP {response.status}'})
            except (
                HTTPError,
                URLError,
                TimeoutError,
                ValueError,
                HTTPException,
                RemoteDisconnected,
                ConnectionError,
                OSError,
            ) as error:
                if attempts is not None:
                    attempts.append({'url': url, 'method': method, 'result': f'{type(error).__name__}: {error}'})
                certificate_error = certificate_error or 'CERTIFICATE_VERIFY_FAILED' in str(error)
                continue
        if certificate_error:
            return Command._request_with_windows_stack(url, timeout, attempts=attempts)
        return None

    @staticmethod
    def _request_with_windows_stack(url, timeout, *, attempts=None):
        if os.name != 'nt':
            return None
        script = (
            '$ErrorActionPreference = "Stop"; '
            '$response = Invoke-WebRequest -Uri $env:MANNIU_VERIFY_URL -Method Head '
            '-MaximumRedirection 10 -TimeoutSec $env:MANNIU_VERIFY_TIMEOUT -UseBasicParsing; '
            'Write-Output (\"{0}|{1}\" -f $response.StatusCode, '
            '$response.BaseResponse.ResponseUri.AbsoluteUri)'
        )
        try:
            environment = os.environ.copy()
            environment['MANNIU_VERIFY_URL'] = url
            environment['MANNIU_VERIFY_TIMEOUT'] = str(max(1, int(timeout)))
            result = subprocess.run(
                ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                capture_output=True,
                text=True,
                timeout=timeout + 2,
                check=False,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            if attempts is not None:
                attempts.append({'url': url, 'method': 'PowerShell HEAD', 'result': f'{type(error).__name__}: {error}'})
            return None
        output = result.stdout.strip()
        if result.returncode != 0 or '|' not in output:
            if attempts is not None:
                detail = result.stderr.strip() or f'exit code {result.returncode}'
                attempts.append({'url': url, 'method': 'PowerShell HEAD', 'result': detail})
            return None
        status, final = output.split('|', 1)
        parsed = urlparse(final)
        if status.isdigit() and 200 <= int(status) < 400 and parsed.scheme in {'http', 'https'} and parsed.netloc:
            if attempts is not None:
                attempts.append({'url': url, 'method': 'PowerShell HEAD', 'result': f'{status} -> {final}'})
            return final
        return None
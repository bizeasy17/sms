export function resolveCompanyWebsiteUrl(websiteUrl: unknown, website: unknown): string {
    const normalizedUrl = String(websiteUrl || '').trim()
    if (normalizedUrl) {
        return normalizedUrl
    }

    const rawWebsite = String(website || '').trim().replace(/\s+/g, '')
    if (!rawWebsite) {
        return ''
    }
    if (/^https?:\/\//i.test(rawWebsite)) {
        return rawWebsite
    }
    return `https://${rawWebsite}`
}
# 慢牛项目部署到 Mac mini

本文说明如何将 `manniu_backend` 和 `manniu_frontend` 部署到家中的 Mac mini，并通过 `www.manniuniu.cn` 从外网访问。

## 1. 推荐架构

```text
浏览器
  |
  | HTTPS
  v
Cloudflare DNS / Cloudflare Tunnel
  |
  | 仅 Mac mini 主动出站连接，不需要向公网暴露家庭公网 IP
  v
Caddy :8080
  |-- /api/*、/<ADMIN_URL_PREFIX>/*、/health/* -> Gunicorn 127.0.0.1:8000
  `-- 其他路径 -> 前端 dist/
                         |
                         `-- Django -> PostgreSQL 127.0.0.1:5432
```

推荐使用 Cloudflare Tunnel，原因是家庭宽带常见动态公网 IP、运营商封禁入站端口或处于 CGNAT。若不希望使用 Cloudflare，也可以改用公网 IP/DDNS + 路由器端口转发，见文末替代方案。

### HTTPS 证书边界

- **Cloudflare Tunnel 方案（本文推荐）**：Mac mini 不需要安装公网证书。用户浏览器访问 `https://www.manniuniu.cn` 时使用的是 Cloudflare Edge 证书；Tunnel 到 Mac 的服务地址是本机 `http://127.0.0.1:8080`，流量不经过家庭网络外部。
- **直连公网方案**：如果路由器将 80/443 转发到 Mac，并让 Caddy直接对外提供 `www.manniuniu.cn`，则需要 Caddy 在 Mac 上申请、保存和自动续期证书。域名 DNS 必须解析到家庭公网 IP，80/443 也必须能从公网访问。
- 不要把自签名证书用于面向普通用户的公网 HTTPS；浏览器会显示不受信任警告。Cloudflare Tunnel 方案也不需要为了“看起来有 HTTPS”而在本机额外生成自签名证书。

## 2. 部署前确认

- Mac mini 能持续运行，并关闭自动睡眠：系统设置 -> 节能/锁定屏幕，设置为接通电源时不自动睡眠。
- Mac mini 使用固定局域网地址，例如 `192.168.1.50`，便于本地维护。
- 域名 `manniuniu.cn` 的 DNS 可以迁移到 Cloudflare。Cloudflare Tunnel 方案不要求路由器转发 80/443。
- 项目使用 PostgreSQL，不要改成 SQLite。后台依赖见 `manniu_backend/requirements.txt`。
- 生产环境不要运行 Vite `npm run dev`，应使用 `npm run build` 生成静态文件。

## 3. Mac mini 基础环境

在 Mac 上安装 Xcode Command Line Tools、Homebrew、Python 和 Node.js：

```bash
xcode-select --install
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew update
brew install python@3.12 node postgresql@16 caddy cloudflared git
```

确认架构和版本：

```bash
uname -m
python3 --version
node --version
psql --version
```

Apple Silicon 推荐使用原生 arm64 工具链，不要混用 Rosetta 下的 Python、Node 和 PostgreSQL。

启动 PostgreSQL 并创建数据库用户。密码请替换为随机强密码，不要使用示例值：

```bash
brew services start postgresql@16
createuser -s manniu_app
createdb -O manniu_app manniu
psql -d postgres -c "ALTER ROLE manniu_app WITH LOGIN PASSWORD '替换为随机强密码';"
```

如果数据库已经存在，不要重复执行 `createdb`，先用 `psql -l` 检查。

## 4. 获取代码

建议使用 Git 拉取代码，不要把 Windows 工作区中的 `.env` 直接复制到 Mac：

```bash
sudo mkdir -p /opt/manniu
sudo chown -R "$(id -un)":staff /opt/manniu
git clone <你的私有仓库地址> /opt/manniu
cd /opt/manniu
```

如果暂时没有远程仓库，可通过加密 U 盘或 SSH 复制源码，但必须排除以下内容后再传输：

- `manniu_backend/.env`
- `manniu_frontend/node_modules/`
- `manniu_frontend/dist/`
- 运行日志、数据库导出文件和任何包含 Token 的文件

## 5. 后台 Python 环境

```bash
cd /opt/manniu/manniu_backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel
pip install -r requirements.txt
pip install gunicorn
```

`gunicorn` 当前不在项目依赖文件中，因此本机部署必须额外安装；建议后续将固定版本加入 `requirements.txt`，例如 `gunicorn==23.0.0`，并重新安装验证。

## 6. 生产环境变量

创建 `/opt/manniu/manniu_backend/.env`，权限设为仅当前用户可读：

```bash
cd /opt/manniu/manniu_backend
touch .env
chmod 600 .env
nano .env
```

填写以下模板，所有 `替换...` 内容都必须改掉：

```dotenv
DEBUG=false
SECRET_KEY=替换为至少50位随机值
DB_ENGINE=django.db.backends.postgresql
DB_NAME=manniu
DB_USER=manniu_app
DB_PASSWORD=替换为数据库强密码
DB_HOST=127.0.0.1
DB_PORT=5432
TUSHARE_TOKEN=填写你自己的Token
AUTH_TOKEN_HASH_SECRET=替换为另一组随机值
AUTH_COOKIE_SECURE=true
SECURE_SSL_REDIRECT=true
AUTH_ALLOWED_CORS_ORIGINS=https://www.manniuniu.cn
PREDICTIVE_VALUATION_ENABLED=false
```

生成随机值示例：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

不要把 `.env` 加入仓库。确认 `.gitignore` 已覆盖它；若没有，补充：

```gitignore
manniu_backend/.env
```

### 6.1 必须完成的 Django 配置前置修改

当前 `config/settings.py` 中 `ALLOWED_HOSTS = []`，生产请求会被 Django 拒绝。部署前将其改为读取环境变量，并增加 CSRF 来源：

```python
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get('ALLOWED_HOSTS', '').split(',')
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
]

STATIC_ROOT = BASE_DIR / 'staticfiles'

# Cloudflare Tunnel 将浏览器的 HTTPS 请求转发到本机后，Django 仍需信任
# 反向代理传递的协议头，避免 HTTPS 被识别成 HTTP。
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
```

然后在 `.env` 增加：

```dotenv
ALLOWED_HOSTS=www.manniuniu.cn,manniuniu.cn,127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=https://www.manniuniu.cn,https://manniuniu.cn
ADMIN_URL_PREFIX=control-7f3a9c2d
```

这项修改属于生产配置必需项，不要用 `ALLOWED_HOSTS=*` 或 `CSRF_TRUSTED_ORIGINS=*` 绕过检查。

## 7. 数据库迁移和后台验证

首次部署执行：

```bash
cd /opt/manniu/manniu_backend
source .venv/bin/activate
python manage.py check --deploy
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

如果已有 Windows/UAT 数据，需要先在源环境导出，再传到 Mac，确认备份可恢复后导入：

```bash
pg_dump -Fc -h <源数据库地址> -U <源数据库用户> manniu > /tmp/manniu.dump
pg_restore --clean --if-exists -h 127.0.0.1 -U manniu_app -d manniu /tmp/manniu.dump
```

不要在没有备份的情况下使用 `--clean`。迁移和数据导入后检查：

```bash
curl -i -H 'Host: www.manniuniu.cn' -H 'X-Forwarded-Proto: https' http://127.0.0.1:8000/health/
```

## 8. 历史主数据回填顺序

数据库建表和 Django migration 完成后，不要直接运行估值脚本。历史回填必须按依赖顺序执行：主数据 -> 行情 -> 财务 -> 数据质量修复 -> 行业映射 -> 估值。所有回填都可能耗时较长，并受 Tushare 配额和网络稳定性影响；每一步都应确认日志成功后再进入下一步。

### 8.1 Windows 脚本与 macOS 的区别

`manniu_backend/scripts` 下现有文件是 Windows `.bat`，macOS 不能直接执行。Windows/UAT 环境可以使用这些入口，Mac mini 应将每个 `.bat` 中的 `manage.py ...` 命令迁移为 Bash，并统一使用：

```bash
cd /opt/manniu/manniu_backend
source .venv/bin/activate
python manage.py <command> <options>
```

不要把 Windows 的 `C:\Users\...\Scripts\python.exe`、反斜杠路径或 `.bat` 控制语法复制到 Mac。Mac 上建议创建 `scripts/macos/`，为每个阶段保存 `.sh` 文件，并使用：

```bash
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
cd "$PROJECT_ROOT"

"$PYTHON" manage.py <command> <options>
```

执行前赋予权限：`chmod +x scripts/macos/*.sh`。脚本中的 Token、数据库密码和 `.env` 不得写入 Git。

### 8.2 推荐的一次性回填顺序

| 顺序 | Windows 入口 | Mac 执行阶段 | 作用和依赖 |
|---:|---|---|---|
| 1 | `market_data_init.bat` | `market-data-init.sh` | 证券主表、指数主表、公司资料、股票/指数历史行情、每日基本面和筹码成本；所有后续步骤的基础。 |
| 2 | `stock_fundamental_history.bat check`、`stock_cost_history.bat check` | 对应 `repair_*` 命令的只读检查 | 检查历史基本面和筹码成本相对股票日线是否存在缺口；先只读检查，不要直接 backfill。 |
| 3 | 两个 history 脚本的 `backfill` | 对应 `repair_*` 命令 | 仅对第 2 步确认的缺口回填；依赖证券主表和股票日线。默认全市场可能耗时很长。 |
| 4 | `financial_data_init.bat` | `financial-init.sh` | 按披露日期、利润表、资产负债表、现金流量表、财务指标、业绩预告、业绩快报、分红、审计意见和主营业务顺序回填近 5 年财务数据。 |
| 5 | `annual.bat` | `annual.sh` | 发布申万行业映射和规则，并刷新主营业务行业匹配；应放在财务主营业务数据完成后。首次初始化执行一次，之后每年执行。 |
| 6 | `traditional_valuation.bat backfill` | `traditional-valuation-backfill.sh` | 基于历史披露事件、行情、财务和行业模板生成传统估值历史；依赖前 1-5 步。 |
| 7 | `predictive_valuation.bat backfill` | `predictive-valuation-backfill.sh` | 先回填预测特征，再生成预测估值历史；依赖财务历史、股票行情、模型文件和风险数据目录。 |

推荐的阶段日志目录：`/opt/manniu/log/bootstrap/`。每个脚本使用独立日志文件，并在失败时停止，不要用 `|| true` 掩盖错误。

### 8.3 Mac 上的执行模板

以下是阶段编排模板，不是可直接替代所有业务参数的最终脚本。应根据当前 manage.py 命令的 `--help` 结果补齐日期、范围和报告类型：

```bash
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=/opt/manniu/manniu_backend
PYTHON="$PROJECT_ROOT/.venv/bin/python"
LOG_DIR=/opt/manniu/log/bootstrap
mkdir -p "$LOG_DIR"
cd "$PROJECT_ROOT"

run_stage() {
  local name="$1"
  shift
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] START $name"
  "$PYTHON" manage.py "$@" 2>&1 | tee "$LOG_DIR/${name}_$(date '+%Y%m%d_%H%M%S').log"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] DONE $name"
}

# 1. 主数据、行情和基础市场数据
run_stage market_data_init sync_market_data --dataset security-master --mode backfill --scope all
run_stage index_master sync_market_data --dataset index-master --mode backfill --scope all
run_stage company_profile sync_market_data --dataset company-profile --mode backfill --scope all
run_stage stock_bars sync_market_data --dataset stock-bars --mode backfill --scope all
run_stage stock_fundamentals sync_market_data --dataset stock-fundamentals --mode backfill --scope all
run_stage stock_cost sync_market_data --dataset stock-cost --mode backfill --scope all
CORE_INDICES='000001.SH,399001.SZ,000300.SH,000016.SH,000905.SH,399005.SZ,399006.SZ'
run_stage index_bars sync_market_data --dataset index-bars --mode backfill --scope ts-code --ts-codes "$CORE_INDICES"
run_stage index_fundamentals sync_market_data --dataset index-fundamentals --mode backfill --scope ts-code --ts-codes "$CORE_INDICES"

# 2. 财务历史；10 个 endpoint 按顺序执行
for endpoint in disclosure_date income_vip balancesheet_vip cashflow_vip fina_indicator_vip forecast_vip express_vip dividend fina_audit fina_mainbz_vip; do
  run_stage "financial_${endpoint}" sync_financials --mode backfill --scope all --endpoints "$endpoint"
done

# 3. 行业映射和主营业务行业匹配
run_stage sync_sw_industry_mapping sync_sw_industry_mapping \
  --from-tushare \
  --rules-file market_data/static/industry_config/industry_regime_rules_CN.json
run_stage refresh_business_matches traditional_valuation refresh-business-matches --business-match-topn 3

# 4. 传统估值历史；全市场 5 年、全部报告类型
run_stage traditional_validate traditional_valuation validate
run_stage traditional_backfill traditional_valuation backfill \
  --scope all \
  --report-types 'Q1,H1,Q3,FY' \
  --history-years 5 \
  --limit 0 \
  --historical-disclosures

# 5. 预测估值历史；必须先特征、后估值
run_stage predictive_validate predictive_valuation validate
run_stage predictive_backfill_features predictive_valuation backfill-features \
  --scope all \
  --history-years 5 \
  --limit 0
run_stage predictive_backfill_valuations predictive_valuation backfill-valuations \
  --scope all \
  --report-types 'Q1,H1,Q3,FY' \
  --anchor-mode live_latest \
  --history-years 5 \
  --limit 0
```

上面的命令对应当前 `.bat` 文件的默认 5 年全市场模式。首次部署前先用每个命令的 `--help` 和小范围 `--scope ts-code --ts-codes <代码>` 做单股票/少量标的试运行，再执行全市场回填。日期窗口、报告类型和 `anchor-mode` 应根据目标历史范围调整，不要盲目复制示例。

数据质量检查和缺口回填使用以下原生命令，不需要执行 Windows `.bat`：

```bash
# 只读检查
run_stage repair_fundamentals_check repair_stock_fundamentals
run_stage repair_cost_check repair_stock_cost_history

# 确认存在缺口后才执行写入；--execute 是写入开关
run_stage repair_fundamentals_backfill repair_stock_fundamentals --execute --batch-size 50
run_stage repair_cost_backfill repair_stock_cost_history --execute --batch-size 50
```

如果要限定历史窗口，在对应命令后增加 `--start-date YYYYMMDD --end-date YYYYMMDD`。检查命令默认只读；回填命令会修改数据库，必须先确认备份和日志目录可用。

### 8.4 各阶段的注意事项

- `market_data_init.bat` 是第一次市场数据初始化入口；`daily.bat` 是增量任务，不要用它代替首次历史回填。
- `financial_data_init.bat` 已包含 10 个财务端点；`financial_disclosure_backfill.bat` 和 `financial_dividend_init.bat` 是专项补偿入口，正常初始化不要重复执行。若单独使用，Mac 上直接执行对应的 `sync_financials` 命令即可，不要照搬其中 Windows 的 `PROJECT_ROOT`。
- `stock_fundamental_history.bat` 和 `stock_cost_history.bat` 必须先 `check`，再针对缺口 `backfill`；不要把“检查”误当成已经完成回填。
- `traditional_valuation.bat` 的历史模式要显式使用 `backfill`，不要使用默认的 `refresh`；全市场不限量任务可能需要长时间运行。
- `predictive_valuation.bat` 的历史模式也要显式使用 `backfill`，并确认模型文件、配置文件和风险数据目录已经从代码仓库或安全备份部署到 Mac。
- `annual.bat` 的实际顺序是 `sync_sw_industry_mapping` 后执行 `traditional_valuation refresh-business-matches --business-match-topn 3`；行业规则文件位于 `market_data/static/industry_config/industry_regime_rules_CN.json`。
- `monthly.bat` 当前没有实际初始化任务；`daily.bat` 只用于后续增量同步，不要把它们当作历史回填入口。
- 每一阶段都可能部分写入数据库。失败后先查看日志和数据库覆盖情况，再从失败阶段继续，不要未经检查重复全量导入。

### 8.5 每阶段完成后的最小检查

```bash
cd /opt/manniu/manniu_backend
source .venv/bin/activate
python manage.py check
curl -fsS -H 'Host: www.manniuniu.cn' -H 'X-Forwarded-Proto: https' http://127.0.0.1:8000/health/
```

历史主数据回填结束后，再执行一次前端构建、`collectstatic` 和公网验收。不要在回填期间让 GitHub Actions 自动发布新版本；建议先暂停自动部署，完成初始化并备份数据库后再恢复。

### 8.6 macOS daily 定时任务

Windows 的 `daily.bat` 在 macOS 上对应仓库中的 `scripts/macos/daily.sh`。它保留原脚本的完整顺序：证券主表、指数主表、公司资料、股票行情、股票基本面、股票成本、核心指数行情、核心指数基本面、申万行业日数据、市场事件、当日披露财务、传统估值事件和预测估值事件。

先在 Mac 上赋予执行权限并手动试运行一次：

```bash
cd /opt/manniu/manniu_backend
chmod +x scripts/macos/daily.sh
scripts/macos/daily.sh
```

确认手动运行成功后，使用当前部署用户编辑 crontab：

```bash
crontab -e
```

推荐在每天北京时间 20:30 执行，给收盘数据和当日披露留出同步时间：

```cron
SHELL=/bin/bash
PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
30 20 * * 1-5 /opt/manniu/manniu_backend/scripts/macos/daily.sh
```

Intel Mac 如果 Homebrew 安装在 `/usr/local/bin`，保留该路径；Apple Silicon 通常使用 `/opt/homebrew/bin`。cron 使用 Mac mini 的系统时区；执行 `systemsetup -gettimezone` 确认时区，若不是中国时区，应调整时间或改用 launchd。

查看任务是否安装：

```bash
crontab -l
tail -f /opt/manniu/manniu_backend/log/daily/cron.log
```

脚本使用原子目录锁，若上一次任务仍在运行，下一次会记录并退出，不会并发写入同一批数据。每次运行生成独立日志：
`/opt/manniu/manniu_backend/log/daily/daily_YYYYMMDD_HHMMSS.log`。

cron 不读取交互式 shell 配置，但 Django 会从 `manniu_backend/.env` 读取数据库、Tushare 和安全配置；因此 `.env` 必须由运行 cron 的同一 macOS 用户可读。脚本失败会返回非零退出码，但 cron 默认不会主动发邮件；建议定期检查日志，或后续接入监控告警。

不建议在历史主数据首次回填期间启用此任务。历史回填完成、数据库备份完成并通过 `python manage.py check` 后再安装 cron，避免 daily 与全量回填同时访问 Tushare 和数据库。

## 9. 构建前端

前端已经支持生产环境使用相对 API 路径。创建生产环境文件 `/opt/manniu/manniu_frontend/.env.production`：

```dotenv
VITE_API_BASE_URL=/api/v1
```

构建并检查产物：

```bash
cd /opt/manniu/manniu_frontend
npm ci
npm run lint
npm run test
npm run build
test -f dist/index.html
```

## 10. 用 Gunicorn 启动 Django

先手动验证后台：

```bash
cd /opt/manniu/manniu_backend
source .venv/bin/activate
gunicorn config.wsgi:application \
  --bind 127.0.0.1:8000 \
  --workers 2 \
  --access-logfile - \
  --error-logfile -
```

另开终端执行 `curl -i -H 'Host: www.manniuniu.cn' -H 'X-Forwarded-Proto: https' http://127.0.0.1:8000/health/`。验证完成后按 `Ctrl-C` 停止临时进程。个人 Mac mini 建议从 2 个 worker 起步，观察内存后再调整。

## 11. 配置 Caddy 反向代理

创建 `/opt/manniu/Caddyfile`：

```caddyfile
127.0.0.1:8080 {
    encode gzip

    handle /api/* {
      reverse_proxy 127.0.0.1:8000 {
        header_up X-Forwarded-Proto https
      }
    }

    handle /static/* {
      root * /opt/manniu/manniu_backend/staticfiles
      file_server
    }

    handle /control-7f3a9c2d/* {
      reverse_proxy 127.0.0.1:8000 {
        header_up X-Forwarded-Proto https
      }
    }

    handle /health/* {
      reverse_proxy 127.0.0.1:8000 {
        header_up X-Forwarded-Proto https
      }
    }

    handle {
        root * /opt/manniu/manniu_frontend/dist
        try_files {path} /index.html
        file_server
    }
}
```

站点绑定在 `127.0.0.1:8080`，只允许 Mac 本机上的 Cloudflare Tunnel 访问，避免同一 Wi-Fi 下的其他设备直接访问 Caddy。每个 Django 反代规则都显式传递 `X-Forwarded-Proto: https`，与上面的 `SECURE_PROXY_SSL_HEADER` 配合，避免 Django 发生 HTTPS 重定向循环。

启动并本地验证：

```bash
caddy validate --config /opt/manniu/Caddyfile
caddy run --config /opt/manniu/Caddyfile
curl -I http://127.0.0.1:8080/
curl -i http://127.0.0.1:8080/health/
```

确认临时验证通过后，让 Homebrew 服务使用这份配置（不要直接假设它会读取 `/opt/manniu/Caddyfile`）：

```bash
brew services stop caddy
cp /opt/manniu/Caddyfile "$(brew --prefix)/etc/Caddyfile"
brew services start caddy
```

## 12. 混淆 Django Admin 公网路径

不建议直接使用默认的 `/admin/`。可以将后台路径改成只有管理员知道的随机路径，例如：

```text
https://www.manniuniu.cn/control-7f3a9c2d/
```

这只是降低自动扫描和误访问概率，不是安全认证。仍然必须使用强密码、HTTPS 和 Cloudflare Access。

### 12.1 修改 Django 路由

编辑 `manniu_backend/config/urls.py`，增加 `import os`，并将固定的 Admin 路由改为读取环境变量。保留文件中原有的其他 API 路由：

```python
import os

from django.contrib import admin
from django.urls import include, path

admin_url_prefix = os.environ.get('ADMIN_URL_PREFIX', '').strip().strip('/')
if not admin_url_prefix:
    raise RuntimeError('ADMIN_URL_PREFIX must be configured')

urlpatterns = [
    path(f'{admin_url_prefix}/', admin.site.urls),
    # 这里继续保留原有的其他 path(...) 路由
]
```

将原来的 `path('admin/', admin.site.urls)` 删除，不要同时保留默认入口，否则 `/admin/` 仍然可用。`ADMIN_URL_PREFIX` 只填写路径片段，不要带前导或结尾 `/`，例如：

```dotenv
ADMIN_URL_PREFIX=control-7f3a9c2d
```

建议为生产环境生成一段新的随机路径，不要使用项目名、生日或简单的 `backend`、`manage` 等词。修改后重启 Gunicorn。

先在 Mac 上创建管理员账号并收集静态文件：

```bash
cd /opt/manniu/manniu_backend
source .venv/bin/activate
python manage.py createsuperuser
python manage.py collectstatic --noinput
```

然后确认 Caddy 配置已包含与 `ADMIN_URL_PREFIX` 完全一致的规则，以及 `/static/*` 规则，并重启服务：

```bash
brew services restart caddy
curl -I https://www.manniuniu.cn/control-7f3a9c2d/login/
```

登录时使用 `createsuperuser` 创建的账号。不要为 Admin 创建共享账号，不要关闭 Django CSRF 校验，也不要把后台端口 `8000` 或 PostgreSQL `5432` 转发到路由器。

### 推荐：使用 Cloudflare Access 再加一层保护

仅靠 Django 密码也能工作，但 Admin 是高价值攻击入口。建议在 Cloudflare 控制台创建 Access Application：

1. 进入 **Zero Trust -> Access -> Applications -> Add application -> Self-hosted**。
2. 应用域名填写 `www.manniuniu.cn/control-7f3a9c2d/*`，其中路径必须和 `ADMIN_URL_PREFIX`、Caddy 配置一致。
3. 只允许自己的邮箱或指定身份组访问，启用一次性验证码或其他强身份验证。
4. 保存后先通过手机网络访问 Admin，确认会先出现 Cloudflare Access 登录，再出现 Django Admin 登录。

如果暂时不使用 Cloudflare Access，至少应使用唯一的强管理员密码、开启多因素登录（若项目后续接入 MFA）、限制 Django 管理员数量，并定期查看后台和 Cloudflare 访问日志。

## 13. 配置 Cloudflare Tunnel 和域名

1. 在 Cloudflare 添加 `manniuniu.cn`，按 Cloudflare 指引将域名注册商的 Nameserver 改成 Cloudflare 提供的两个地址。
2. 登录 Mac：

   ```bash
   cloudflared tunnel login
   cloudflared tunnel create manniu-home
   ```

3. 创建 `~/.cloudflared/config.yml`：

   ```yaml
   tunnel: <cloudflared输出的Tunnel UUID>
   credentials-file: /Users/<mac用户名>/.cloudflared/<Tunnel UUID>.json

   ingress:
     - hostname: www.manniuniu.cn
       service: http://127.0.0.1:8080
     - hostname: manniuniu.cn
       service: http://127.0.0.1:8080
     - service: http_status:404
   ```

4. 绑定 DNS：

   ```bash
   cloudflared tunnel route dns manniu-home www.manniuniu.cn
   cloudflared tunnel route dns manniu-home manniuniu.cn
   ```

  检查 Tunnel 配置和路由：

  ```bash
  cloudflared tunnel ingress validate
  cloudflared tunnel ingress rule https://www.manniuniu.cn/
  ```

5. 启动隧道并测试：

   ```bash
   cloudflared tunnel run manniu-home
   curl -I https://www.manniuniu.cn/
   curl -i https://www.manniuniu.cn/health/
   ```

Cloudflare Tunnel 方案的浏览器到 Cloudflare 链路必须是 HTTPS；Cloudflare Tunnel 到本机 `127.0.0.1` 使用 HTTP 是可接受的，因为该段流量不离开 Mac。Cloudflare 控制台开启 **Always Use HTTPS**，并先确认 HTTPS 正常后再启用 HSTS。Tunnel 方案不要求在 Mac 上配置证书；如果 Cloudflare 控制台显示 SSL/TLS 模式选项，不要使用 `Flexible`。`Full (strict)`主要用于 Cloudflare 直接回源到 HTTPS Origin，不能据此推断本机的 Tunnel HTTP 服务必须配置证书。

Cloudflare Tunnel 不等于 Django 自动知道原始请求是 HTTPS。必须确认 `SECURE_PROXY_SSL_HEADER`、`SECURE_SSL_REDIRECT=true` 和 Caddy/Cloudflare 的 `X-Forwarded-Proto` 传递正确，否则可能出现 HTTPS 重定向循环。外网验收：

```bash
curl -I http://www.manniuniu.cn/
curl -I https://www.manniuniu.cn/
curl -I https://www.manniuniu.cn/control-7f3a9c2d/login/
```

第一条应跳转到 `https://www.manniuniu.cn/`，后两条不能出现重定向循环；浏览器开发者工具中 Cookie 应带有 `Secure`、`HttpOnly`（适用时）和合理的 `SameSite` 属性。

## 14. 设置开机自动运行

首次上线建议先手动验证全部链路，再为 Gunicorn、Caddy、Cloudflared 安装 Homebrew 服务：

```bash
brew services start caddy
brew services start cloudflared
```

Gunicorn 建议使用 macOS `launchd`。创建 `~/Library/LaunchAgents/cn.manniuni.backend.plist`，把 `<mac用户名>` 替换为实际用户名：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>cn.manniuni.backend</string>
  <key>WorkingDirectory</key><string>/opt/manniu/manniu_backend</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/manniu/manniu_backend/.venv/bin/gunicorn</string>
    <string>config.wsgi:application</string>
    <string>--bind</string><string>127.0.0.1:8000</string>
    <string>--workers</string><string>2</string>
    <string>--access-logfile</string><string>-</string>
    <string>--error-logfile</string><string>-</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>DJANGO_SETTINGS_MODULE</key><string>config.settings</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/opt/manniu/log/gunicorn.out.log</string>
  <key>StandardErrorPath</key><string>/opt/manniu/log/gunicorn.err.log</string>
</dict>
</plist>
```

执行：

```bash
mkdir -p /opt/manniu/log
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/cn.manniuni.backend.plist
launchctl kickstart -k gui/$(id -u)/cn.manniuni.backend
launchctl print gui/$(id -u)/cn.manniuni.backend
```

更新代码后依次执行：

```bash
cd /opt/manniu
git pull --ff-only
cd manniu_backend && source .venv/bin/activate && pip install -r requirements.txt && python manage.py migrate && python manage.py collectstatic --noinput
cd ../manniu_frontend && npm ci && npm run build
launchctl kickstart -k gui/$(id -u)/cn.manniuni.backend
brew services restart caddy
brew services restart cloudflared
```

## 15. GitHub 新版本自动部署

家用 Mac mini 推荐使用 GitHub Actions self-hosted runner。Runner 由 Mac mini 主动连接 GitHub，因此不需要向公网开放 SSH，也不依赖家庭公网 IP。发布到 `main` 分支后，GitHub Actions 会在 Mac 上执行更新。

### 15.1 创建专用部署账号和工作目录

建议不要使用日常 macOS 管理员账号运行 runner。创建一个只用于部署的本地用户 `manniu-deploy`，并确保它只能访问项目、虚拟环境和部署日志。以下命令需要管理员权限，用户名和路径按实际情况调整：

```bash
sudo sysadminctl -addUser manniu-deploy -password -
sudo mkdir -p /opt/manniu
sudo chown -R manniu-deploy:staff /opt/manniu
```

在该账号下准备项目目录，并确保这是一个专用部署副本：

```bash
sudo -iu manniu-deploy
git clone <你的私有仓库地址> /opt/manniu
cd /opt/manniu
```

将生产 `.env`、Cloudflare 配置、PostgreSQL 凭据等放在 Mac 本地，不提交到 GitHub。部署 runner 不应允许仓库中的普通代码修改这些机密文件。

如果仓库是私有仓库，为部署账号配置只读 Deploy Key：

```bash
sudo -iu manniu-deploy
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/manniu_deploy -C "manniu-macmini-deploy"
cat ~/.ssh/manniu_deploy.pub
```

将输出的公钥添加到 GitHub 仓库 **Settings -> Deploy keys -> Add deploy key**，不要勾选写入权限。然后在 Mac 上配置 SSH：

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com-manniu
  HostName github.com
  User git
  IdentityFile ~/.ssh/manniu_deploy
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
cd /opt/manniu
git remote set-url origin git@github.com-manniu:<组织或用户名>/<仓库名>.git
ssh -T git@github.com-manniu
```

看到 GitHub 的认证成功提示后再安装 runner。私钥只保存在 Mac 上，不要上传到 GitHub、Actions Secrets 或项目目录。

### 15.2 安装 GitHub Actions runner

在 GitHub 仓库进入 **Settings -> Actions -> Runners -> New self-hosted runner**，选择 **macOS** 和 Mac mini 的 CPU 架构，按照 GitHub 页面显示的最新版命令安装。不要复制旧的 registration token；该 token 是一次性的。

安装时添加自定义标签 `manniu-macmini`。完成后先验证 runner 在线，再安装为后台服务：

```bash
./run.sh
```

确认 GitHub 页面显示 `Idle` 后按 `Ctrl-C`，再根据 GitHub 页面提供的 `svc.sh` 命令安装和启动服务。不要用 `sudo` 运行 runner 服务，除非 GitHub 页面针对当前 runner 版本明确要求；让它以 `manniu-deploy` 用户运行。

### 15.3 添加 GitHub Actions 工作流

在项目根目录创建 `.github/workflows/deploy-macmini.yml`，将 `main` 改成你的生产分支：

```yaml
name: Deploy to Mac mini

on:
  push:
    branches: [main]
  workflow_dispatch:

concurrency:
  group: manniu-production
  cancel-in-progress: false

jobs:
  deploy:
    runs-on: [self-hosted, macOS, manniu-macmini]
    timeout-minutes: 30

    steps:
      - name: Update source
        shell: bash
        run: |
          set -euo pipefail
          cd /opt/manniu
          git fetch --prune origin main
          git checkout main
          git reset --hard origin/main

      - name: Backup database
        shell: bash
        run: |
          set -euo pipefail
          mkdir -p /opt/manniu/backups
          pg_dump -Fc -h 127.0.0.1 -U manniu_app manniu \
            > "/opt/manniu/backups/manniu-$(date +%Y%m%d-%H%M%S).dump"

      - name: Update backend
        shell: bash
        run: |
          set -euo pipefail
          cd /opt/manniu/manniu_backend
          source .venv/bin/activate
          pip install -r requirements.txt
          python manage.py check --deploy
          python manage.py migrate
          python manage.py collectstatic --noinput

      - name: Build frontend
        shell: bash
        run: |
          set -euo pipefail
          cd /opt/manniu/manniu_frontend
          npm ci
          npm run lint
          npm run test
          npm run build

      - name: Restart application services
        shell: bash
        run: |
          set -euo pipefail
          launchctl kickstart -k "gui/$(id -u)/cn.manniuni.backend"
          brew services restart caddy
          curl --fail --silent --show-error \
            -H 'Host: www.manniuniu.cn' \
            -H 'X-Forwarded-Proto: https' \
            http://127.0.0.1:8000/health/
          curl --fail --silent --show-error http://127.0.0.1:8080/health/
```

提交工作流后，先在 GitHub Actions 页面手动执行一次 `workflow_dispatch`，确认成功，再合并到 `main` 触发正式发布。生产分支建议启用 branch protection 和 pull request review，不要允许任何人直接推送未经审查的代码。不要让来自外部贡献者的 Pull Request 使用这个 self-hosted runner；该 runner 能访问生产数据库和本地密钥，只允许受保护分支运行部署工作流。

### 15.4 失败处理和回滚

- `npm run lint`、测试、`manage.py check --deploy` 或构建失败时，工作流会停止，不会重启当前服务。
- 数据库迁移成功但后续前端构建失败时，旧进程仍可能继续运行；先检查服务状态，再决定是否回滚代码。
- 回滚代码前先备份当前数据库，然后在 Mac 上执行 `git log` 找到上一个稳定 commit：

  ```bash
  cd /opt/manniu
  git reset --hard <上一个稳定commit>
  cd manniu_backend
  source .venv/bin/activate
  pip install -r requirements.txt
  python manage.py collectstatic --noinput
  cd ../manniu_frontend
  npm ci
  npm run build
  launchctl kickstart -k "gui/$(id -u)/cn.manniuni.backend"
  brew services restart caddy
  ```

不要在部署目录中手工修改代码后再运行自动部署，因为 workflow 的 `git reset --hard origin/main` 会覆盖这些修改。

## 16. 上线验收清单

- `https://www.manniuniu.cn/` 返回前端页面，浏览器开发者工具中 API 请求为同域名 `/api/v1/...`。
- `https://www.manniuniu.cn/health/` 返回成功状态。
- 登录、退出、刷新页面和需要 Cookie 的请求均正常。
- `https://www.manniuniu.cn/control-7f3a9c2d/` 只能通过强密码账户访问。
- Django 日志没有 `DisallowedHost`、CSRF 或数据库连接错误。
- 从手机蜂窝网络访问，而不是只在家中 Wi-Fi 测试。
- Cloudflare Tunnel 重启后仍能恢复连接，Mac 重启后三个服务都能自动启动。

## 17. 备份、更新和安全

每日备份 PostgreSQL，并至少保留一份不在 Mac 上的副本：

```bash
mkdir -p /opt/manniu/backups
pg_dump -Fc -h 127.0.0.1 -U manniu_app manniu > /opt/manniu/backups/manniu-$(date +%Y%m%d-%H%M).dump
```

同时备份以下内容：

- `/opt/manniu/manniu_backend/.env`，使用加密密码库保存，不要放进 Git。
- `~/.cloudflared/` 中的 Tunnel 配置和凭据。
- PostgreSQL dump 和项目配置变更记录。

上线更新前先执行数据库 dump；代码更新使用 `git pull --ff-only`；出现问题时恢复上一个 Git commit、重启 Gunicorn，并从备份恢复数据库。不要在公网开放 PostgreSQL 的 5432 端口、Django 8000 端口或 Caddy 8080 端口。

当前 Windows 工作区中的 `.env` 已包含真实凭据痕迹。若该文件曾经提交到 Git、发送给他人或上传到任何外部服务，应立即轮换 Tushare Token、数据库密码、Django `SECRET_KEY` 和 `AUTH_TOKEN_HASH_SECRET`，再在 Mac 上填写新值。

## 18. 不使用 Cloudflare Tunnel 的替代方案

如果必须直连家庭网络：

1. 为 Mac mini 设置固定局域网 IP。
2. 路由器只转发 TCP 80/443 到 Mac mini；不要转发 8000/5432。
3. 使用 DDNS 解决家庭公网 IP 变化，或确认运营商提供固定公网 IP。
4. 让 Caddy 直接监听 80/443，并将站点名改为 `www.manniuniu.cn`，由 Caddy 自动申请和续期证书。
5. 如果宽带处于 CGNAT，端口转发通常无效，应回到 Cloudflare Tunnel、Tailscale Funnel 或 VPS 反向隧道方案。

直连方案需要额外处理路由器防火墙、证书续期和公网 IP 变化，优先级低于 Cloudflare Tunnel。
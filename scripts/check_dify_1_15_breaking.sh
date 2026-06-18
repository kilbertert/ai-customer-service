#!/usr/bin/env bash
# M11+ P0-B (D6 决策) — Dify 1.15+ 升级前 5 类 breaking change 静态扫描。
#
# 用法: scripts/check_dify_1_15_breaking.sh <dify-1.15.0-src-dir> [dify-1.14.2-migrations-file]
#   - 第一个参数: Dify 1.15.0 源码目录 (e.g. ./dify-1.15.0/)
#   - 第二个参数(可选): Dify 1.14.2 的 migrations list 文件路径,用于 DB 迁移比对
#
# 输出: 5 类逐一命中情况,exit 0 = 全 0 命中,exit 1 = 至少 1 类命中需人工 review
#
# 5 类 (按命中优先级排):
#   1. login       - admin 登录端点路径/参数 (影响 DifyAdminClient._login)
#   2. App schema  - App 模型字段 (影响 create_app_and_workflow 解析)
#   3. API key     - per-app API key endpoint (影响 enable_api_and_create_key)
#   4. multi-tenant - tenant_id / current_tenant (影响 Workspace.dify_tenant_id 过滤)
#   5. DB migration - workflows 表 schema (影响 P0-C Deployer 的 probe_workflows_schema)

set -euo pipefail

SRC="${1:?usage: $0 <dify-src-dir> [dify-1.14.2-migrations-file]}"
OLD_MIG="${2:-}"

if [ ! -d "$SRC" ]; then
    echo "❌ Dify 源码目录不存在: $SRC"
    exit 2
fi

EXIT=0
HITS=0

scan() {
    local label="$1"
    local pattern="$2"
    local dir="$3"

    echo
    echo "[$label] $pattern in $dir"
    local matches
    if matches=$(grep -rEn --include="*.py" "$pattern" "$dir" 2>/dev/null | head -20); then
        if [ -n "$matches" ]; then
            echo "$matches"
            echo "  ⚠️  命中 → 人工 review Dify release notes 是否影响 basjoo 集成"
            HITS=$((HITS + 1))
        else
            echo "  ✅ 0 命中"
        fi
    else
        echo "  ✅ 0 命中"
    fi
}

# 1. login endpoint - admin 登录路径 (DifyAdminClient._login 用)
#    Dify 1.14.2: controllers/console/auth/login.py @console_ns.route("/login")
scan "1/5 login" "console_ns\.route.*\"/login\"|@login_required" "$SRC/api/controllers/console/auth"

# 2. App schema - App 模型字段 (create_app_and_workflow 解析)
#    Dify 1.14.2: models/model.py class App(Base): / class AppModelConfig
scan "2/5 App schema" "^class App\b|class AppModelConfig|app_model_config" "$SRC/api/models"

# 3. API key - per-app API key endpoint (enable_api_and_create_key)
#    Dify 1.14.2: controllers/console/app/app.py @console_ns.route("/apps/<uuid:app_id>/api-enable")
scan "3/5 API key" "api-enable|/api-keys|enable_api" "$SRC/api/controllers/console"

# 4. multi-tenant - tenant 上下文 (Workspace.dify_tenant_id 过滤)
#    Dify 1.14.2: libs/helper.py extract_tenant_id / libs/login.py current_tenant_id
scan "4/5 multi-tenant" "tenant_id|current_tenant_id" "$SRC/api/libs"

# 5. DB migration - workflows 表 schema diff
echo
echo "[5/5] DB migration: workflows table"
if [ -d "$SRC/api/migrations/versions" ]; then
    NEW=$(ls "$SRC/api/migrations/versions" 2>/dev/null | sort)
    echo "$NEW" > /tmp/dify-1.15-migrations-$$.txt
    if [ -n "$OLD_MIG" ] && [ -f "$OLD_MIG" ]; then
        if ! diff -q "$OLD_MIG" /tmp/dify-1.15-migrations-$$.txt >/dev/null 2>&1; then
            echo "  ⚠️  migration 列表 diff (前 20 行):"
            diff "$OLD_MIG" /tmp/dify-1.15-migrations-$$.txt | head -20
            echo "  ⚠️  命中 → 人工 review 是否影响 workflows / apps / tenants 表 schema"
            HITS=$((HITS + 1))
        else
            echo "  ✅ 0 diff"
        fi
    else
        echo "  ℹ️  未提供 1.14.2 migration list,跳过 diff。"
        echo "     当前 1.15.0 migration 文件数: $(echo "$NEW" | wc -l)"
    fi
    rm -f /tmp/dify-1.15-migrations-$$.txt
else
    echo "  ⚠️  Dify 源码无 migrations/versions/ 目录,可能不是标准 Dify 仓库结构"
fi

echo
echo "============================================="
if [ "$HITS" -eq 0 ]; then
    echo "✅ 5/5 0 breaking change detected — 可推进 P0-B Step 8 staging 灰度"
    exit 0
else
    echo "⚠️  $HITS 类命中 — 需人工 review 或 D9 补丁跟进"
    exit 1
fi

#!/usr/bin/env python3
"""Terraform(HCL)→ tech-diagram スペック骨格の自動変換。

使い方:
  python3 tf_to_spec.py <root module ディレクトリ> [-o <name>.spec.json]
                        [--review <name>.review.json] [--state <state.json>]

設計(認証ゼロがデフォルト):
- .tf を直接パースする(terraform CLI・AWS 認証・state 不要)。
  HCL のサブセット(resource/module/variable/locals/data ブロック、属性、
  参照、count/for_each、heredoc・コメントの読み飛ばし)を扱う。
- 出力は 2 つ:
  1) スペック骨格(そのままビルド可能。col/row なし=自動配置に流す)
  2) レビュー情報(エッジ候補・Lambda コード確認リスト・注記)—
     エージェントがここを潰して図を仕上げる
- 「書いてある=使う」を前提とし、例外だけ注記する:
  count/for_each が 0 になり得る条件付きリソース、未参照モジュール。
- --state(terraform state pull / show -json の出力)を渡すと実在照合に
  昇格する。sensitive 値はツール内で捨て、位相情報しか読まない。
  ※state をエージェントが Read で直接開くのは禁止(秘密情報を含むため)。

方針: リソース全部をノードにしない。図に載せる価値のある型だけを
ノード化し、配線・所属情報しか持たない型(IAM・ルートテーブル・
SG ルール等)はエッジ/所属の材料として消費する。未知の型は review に
回してエージェントが判断する。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# ---- リソース型 → アイコン(図に載せる価値がある型だけ) ----
NODE_ICONS = {
    "aws_lambda_function": "lambda",
    "aws_dynamodb_table": "dynamodb",
    "aws_s3_bucket": "s3",
    "aws_instance": "ec2",
    "aws_db_instance": "rds",
    "aws_rds_cluster": "aurora",
    "aws_elasticache_cluster": "elasticache",
    "aws_elasticache_replication_group": "elasticache",
    "aws_sqs_queue": "sqs",
    "aws_sns_topic": "sns",
    "aws_api_gateway_rest_api": "api_gateway",
    "aws_apigatewayv2_api": "api_gateway",
    "aws_cloudwatch_event_bus": "eventbridge",
    "aws_cloudwatch_event_rule": "eventbridge",
    "aws_scheduler_schedule": "eventbridge_scheduler",
    "aws_kinesis_stream": "kinesis_data_streams",
    "aws_kinesis_firehose_delivery_stream": "kinesis_data_firehose",
    "aws_sfn_state_machine": "step_functions",
    "aws_ecs_cluster": "ecs",
    "aws_ecs_service": "ecs_service",
    "aws_eks_cluster": "eks",
    "aws_lb": "application_load_balancer",
    "aws_alb": "application_load_balancer",
    "aws_elb": "elastic_load_balancing",
    "aws_cloudfront_distribution": "cloudfront",
    "aws_route53_zone": "route_53",
    "aws_route53_record": "route_53",
    "aws_cognito_user_pool": "cognito",
    "aws_ecr_repository": "ecr",
    "aws_opensearch_domain": "elasticsearch_service",
    "aws_elasticsearch_domain": "elasticsearch_service",
    "aws_efs_file_system": "efs",
    "aws_nat_gateway": "nat_gateway",
    "aws_internet_gateway": "internet_gateway",
    "aws_vpn_gateway": "site_to_site_vpn",
    "aws_dx_connection": "direct_connect",
    "aws_ec2_transit_gateway": "transit_gateway",
    "aws_glue_job": "glue",
    "aws_athena_workgroup": "athena",
    "aws_redshift_cluster": "redshift",
    "aws_mq_broker": "mq",
    "aws_msk_cluster": "managed_streaming_for_kafka",
    "aws_secretsmanager_secret": "secrets_manager",
    "aws_kms_key": "key_management_service",
    "aws_backup_vault": "backup",
    "aws_codepipeline": "codepipeline",
    "aws_codebuild_project": "codebuild",
    "aws_amplify_app": "amplify",
    "aws_appsync_graphql_api": "appsync",
    "aws_batch_job_queue": "batch",
    "aws_sagemaker_endpoint": "sagemaker",
    "aws_wafv2_web_acl": "waf",
    "aws_globalaccelerator_accelerator": "global_accelerator",
}

# 配線・所属の材料としてだけ使う型(ノードにしない。review にも出さない)
PLUMBING_TYPES_PREFIX = (
    "aws_iam_", "aws_route_table", "aws_route.", "aws_security_group",
    "aws_vpc_security_group", "aws_lambda_permission",
    "aws_lambda_event_source_mapping", "aws_api_gateway_", "aws_apigatewayv2_",
    "aws_s3_bucket_", "aws_cloudwatch_log_", "aws_sns_topic_subscription",
    "aws_cloudwatch_event_target", "aws_lambda_function_event_invoke_config",
    "aws_acm_", "aws_route53_health_check", "aws_db_subnet_group",
    "aws_elasticache_subnet_group", "aws_ecs_task_definition",
    "aws_appautoscaling_", "aws_lb_", "aws_alb_", "aws_lambda_alias",
    "aws_lambda_layer_version", "aws_sqs_queue_policy", "aws_sns_topic_policy",
    "aws_vpc_endpoint", "aws_eip", "aws_network_", "aws_flow_log",
    "aws_subnet.", "aws_vpc.", "aws_scheduler_schedule_group",
    "aws_cognito_user_pool_client", "aws_cognito_user_pool_domain",
    "random_", "null_", "local_file", "archive_file", "time_", "tls_",
)

# コンテナになる型
CONTAINER_TYPES = {"aws_vpc": "vpc", "aws_subnet": None}  # subnet は pub/priv 判定

REF_RE = re.compile(
    r"\b((?:aws|random|null|archive|local|time|tls)_[a-z0-9_]+\.[\w-]+"
    r"|module\.[\w-]+(?:\.[\w-]+)?|var\.[\w-]+|local\.[\w-]+|data\.[\w.-]+)")

ASYNC_HINTS = ("sqs", "sns", "event", "kinesis", "firehose", "stream", "msk")


# ==================================================================
# HCL サブセットパーサ
# ==================================================================

class Block:
    __slots__ = ("btype", "labels", "attrs", "blocks", "path", "prefix")

    def __init__(self, btype, labels, path):
        self.btype = btype
        self.labels = labels
        self.attrs: dict[str, str] = {}
        self.blocks: list[Block] = []
        self.path = path
        self.prefix = ""

    def find(self, btype):
        return [b for b in self.blocks if b.btype == btype]


def _strip_comments(text: str) -> str:
    """コメントと heredoc 本文を除去する(位相抽出に不要)。文字列は保持。"""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':                          # 文字列(${} 内の " も素通し)
            j = i + 1
            depth = 0
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j:j + 2] == "${":
                    depth += 1
                    j += 2
                    continue
                if depth and text[j] == "}":
                    depth -= 1
                elif not depth and text[j] == '"':
                    break
                j += 1
            out.append(text[i:j + 1])
            i = j + 1
        elif c == "#" or text[i:i + 2] == "//":
            while i < n and text[i] != "\n":
                i += 1
        elif text[i:i + 2] == "/*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif text[i:i + 2] == "<<":            # heredoc: 本文を参照抽出対象外に
            m = re.match(r"<<-?([A-Za-z_][\w]*)", text[i:])
            if m:
                tag = m.group(1)
                end = re.search(rf"^\s*{re.escape(tag)}\s*$", text[i:],
                                re.MULTILINE)
                body_end = i + (end.end() if end else len(text) - i)
                out.append(' "<heredoc>"')
                i = body_end
            else:
                out.append(c)
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def parse_hcl(text: str, path: str) -> list[Block]:
    """トップレベルのブロック列を返す(属性は生の式文字列)。"""
    text = _strip_comments(text)
    pos = [0]
    n = len(text)

    def skip_ws():
        while pos[0] < n and text[pos[0]] in " \t\r\n,":
            pos[0] += 1

    NEXT_ATTR = re.compile(r"[ \t]+[A-Za-z_][\w-]*[ \t]*=(?!=)")

    def read_expr_until(stop_at_newline: bool) -> str:
        """括弧・文字列の深さを見て 1 式を読む。

        depth 0 で「次の属性の開始(ident =)」が見えたらそこで止める
        (1 行に複数属性を詰めた行儀の悪い HCL への頑健性)。"""
        start = pos[0]
        depth = 0
        seen_content = False
        while pos[0] < n:
            c = text[pos[0]]
            if c == '"':
                seen_content = True
                pos[0] += 1
                while pos[0] < n and text[pos[0]] != '"':
                    if text[pos[0]] == "\\":
                        pos[0] += 1
                    pos[0] += 1
            elif c in "([{":
                depth += 1
                seen_content = True
            elif c in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif c == "\n" and depth == 0 and stop_at_newline:
                break
            elif depth == 0 and seen_content and c in " \t" \
                    and NEXT_ATTR.match(text, pos[0]):
                break
            else:
                if c not in " \t":
                    seen_content = True
            pos[0] += 1
        return text[start:pos[0]].strip()

    def parse_body(block: Block, top: bool):
        while True:
            skip_ws()
            if pos[0] >= n:
                return
            if text[pos[0]] == "}":
                if not top:
                    pos[0] += 1
                    return
                pos[0] += 1
                continue
            m = re.match(r'[A-Za-z_][\w-]*', text[pos[0]:])
            if not m:
                pos[0] += 1
                continue
            ident = m.group(0)
            pos[0] += len(ident)
            skip_ws()
            labels = []
            while pos[0] < n and text[pos[0]] == '"':
                lm = re.match(r'"([^"]*)"', text[pos[0]:])
                if not lm:
                    break
                labels.append(lm.group(1))
                pos[0] += lm.end()
                skip_ws()
            if pos[0] < n and text[pos[0]] == "{":
                pos[0] += 1
                child = Block(ident, labels, path)
                parse_body(child, top=False)
                block.blocks.append(child)
            elif pos[0] < n and text[pos[0]] == "=":
                pos[0] += 1
                skip_ws()
                block.attrs[ident] = read_expr_until(stop_at_newline=True)
            else:
                pos[0] += 1

    root = Block("<root>", [], path)
    parse_body(root, top=True)
    return root.blocks


# ==================================================================
# モジュール解決・意味付け
# ==================================================================

def load_module(dir_: Path, prefix: str, stack: tuple,
                notes: list[str], called_dirs: set) -> list[Block]:
    """ディレクトリの .tf を読み、ローカルモジュールを再帰展開する。

    循環判定は「現在の展開経路(stack)」で行う。同一モジュールの複数
    インスタンス化(使い回し)は正常なパターンなので、経路上に無ければ
    何度でも展開する(インスタンスごとに prefix が異なる)。
    """
    key = str(dir_.resolve())
    if key in stack:
        notes.append(f"モジュール循環参照: {dir_}(経路上の 2 回目は展開しない)")
        return []
    blocks: list[Block] = []
    for f in sorted(dir_.glob("*.tf")):
        try:
            blocks += parse_hcl(f.read_text(encoding="utf-8", errors="replace"),
                                str(f))
        except RecursionError:
            notes.append(f"パース不能(ネスト過深): {f}")
    out: list[Block] = []
    for b in blocks:
        b.prefix = prefix
        if b.btype == "module" and b.labels:
            src = (b.attrs.get("source") or "").strip().strip('"')
            mdir = (dir_ / src) if src.startswith(".") else None
            if mdir and mdir.is_dir():
                called_dirs.add(str(mdir.resolve()))
                sub = load_module(mdir, f"{prefix}{b.labels[0]}.",
                                  stack + (key,), notes, called_dirs)
                b.labels = [f"{prefix}{b.labels[0]}"]
                out.append(b)
                out.extend(sub)
            else:
                notes.append(f"外部モジュール(展開不可): {prefix}{b.labels[0]}"
                             f" source={src or '?'} — 中身は図に含まれない")
                b.labels = [f"{prefix}{b.labels[0]}"]
                out.append(b)
        else:
            if b.labels and b.btype in ("resource", "data") and prefix \
                    and len(b.labels) > 1:
                b.labels = [b.labels[0], f"{prefix}{b.labels[1]}"]
            out.append(b)
    return out


def rid(b: Block) -> str:
    """resource ブロックの参照 id(aws_lambda_function.api など)。"""
    return f"{b.labels[0]}.{b.labels[1]}" if len(b.labels) > 1 else b.labels[0]


def refs_in(expr: str) -> list[str]:
    out = []
    for r in REF_RE.findall(expr or ""):
        if r.startswith("data."):
            r = ".".join(r.split(".")[:3])   # data.TYPE.NAME に正規化
        elif r.split(".")[0] not in ("module", "var", "local"):
            r = ".".join(r.split(".")[:2])   # TYPE.NAME に正規化
        out.append(r)
    return out


def all_refs(b: Block) -> list[str]:
    out = []
    for v in b.attrs.values():
        out += refs_in(v)
    for c in b.blocks:
        out += all_refs(c)
    return out


def is_plumbing(rtype: str) -> bool:
    probe = rtype + "."
    return any(probe.startswith(p) or rtype.startswith(p.rstrip("."))
               for p in PLUMBING_TYPES_PREFIX)


def var_defaults(blocks: list[Block]) -> dict[str, str]:
    out = {}
    for b in blocks:
        if b.btype == "variable" and b.labels:
            out[f"var.{b.labels[0]}"] = (b.attrs.get("default") or "").strip()
    return out


def count_note(b: Block, defaults: dict[str, str]) -> str | None:
    """count/for_each が 0 になり得るなら注記文字列を返す。"""
    for key in ("count", "for_each"):
        expr = b.attrs.get(key)
        if not expr:
            continue
        if expr.strip() == "0":
            return f"{key}=0(無効化されている)"
        m = re.search(r"(var\.[\w-]+)\s*\?\s*(\d+)", expr)
        if m:
            default = defaults.get(m.group(1), "")
            if default in ("false", '"false"', "0", ""):
                return (f"{key} が {m.group(1)} 依存(default="
                        f"{default or '未設定'})— 環境によっては未適用")
    return None


def sid(name: str) -> str:
    """モジュール接頭辞のドットを含む名前をスペック id 用に無害化。"""
    return name.replace(".", "__")


FOREACH_CAP = 12   # 展開の上限(それ以上は図が破綻するので縮約のまま注記)


def foreach_entries(b: Block, locals_map: dict) -> dict[str, str] | None:
    """for_each のキーと各エントリの生値を静的解決する。

    対応: マップ/リストのリテラル、toset()、local. 参照 1 ホップ。
    解決できなければ None(呼び出し側が縮約+注記にフォールバック)。
    従来は for_each リソースが黙って 1 ノードに縮約され、複数 Lambda が
    1 個に見える取りこぼしがあった。"""
    expr = (b.attrs.get("for_each") or "").strip()
    m = re.fullmatch(r"local\.([\w-]+)", expr)
    if m:
        expr = (locals_map.get((b.prefix, m.group(1))) or "").strip()
    m = re.fullmatch(r"toset\((.*)\)", expr, re.S)
    if m:
        expr = m.group(1).strip()
    if expr.startswith("[") and expr.endswith("]"):
        keys = re.findall(r'"([^"]+)"', expr)
        return {k: "" for k in keys[:FOREACH_CAP]} or None
    if not (expr.startswith("{") and expr.endswith("}")):
        return None
    inner = expr[1:-1]
    entries: dict[str, str] = {}
    depth = 0
    i = 0
    entry_start = True
    cur_key: str | None = None
    val_start = 0

    def close_entry(end: int):
        nonlocal cur_key
        if cur_key is not None:
            entries[cur_key] = inner[val_start:end].strip().rstrip(",")
            cur_key = None

    while i < len(inner):
        c = inner[i]
        if c == '"':
            if entry_start and depth == 0:
                km = re.match(r'"([^"]+)"\s*=', inner[i:])
                if km:
                    close_entry(i)
                    cur_key = km.group(1)
                    entry_start = False
                    i += km.end()
                    val_start = i
                    continue
            j = i + 1
            while j < len(inner) and inner[j] != '"':
                if inner[j] == "\\":
                    j += 1
                j += 1
            i = j + 1
            continue
        if c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
        elif depth == 0:
            if entry_start:
                km = re.match(r"([A-Za-z_][\w-]*)\s*=", inner[i:])
                if km:
                    close_entry(i)
                    cur_key = km.group(1)
                    entry_start = False
                    i += km.end()
                    val_start = i
                    continue
            if c in ",\n":
                entry_start = True
        i += 1
    close_entry(len(inner))
    if len(entries) > FOREACH_CAP:
        entries = dict(list(entries.items())[:FOREACH_CAP])
    return entries or None


def subst_each(expr: str, key: str, entry: str) -> str:
    """`each.value.X` / `each.key` を for_each エントリの実値に置換する
    (ヒント用。解決できない参照はそのまま残す)。"""
    def rep(m):
        vm = re.search(rf'\b{re.escape(m.group(1))}\s*=\s*"([^"]+)"',
                       entry or "")
        return vm.group(1) if vm else m.group(0)
    expr = re.sub(r"each\.value\.([\w-]+)", rep, expr or "")
    return expr.replace("each.key", key)


# 所属解決に使う属性名(部分文字列一致ではなく構造で見る)
SUBNET_ATTRS = frozenset({"subnet_id", "subnet_ids", "subnets"})
VPC_ATTRS = frozenset({"vpc_id"})
GROUP_ATTRS = frozenset({"db_subnet_group_name", "subnet_group_name",
                         "cache_subnet_group_name",
                         "replication_subnet_group_id"})
# 汎用参照候補(attr_ref)から除外する属性(実行時通信を意味しない)
NOISE_ATTRS = frozenset({"tags", "tags_all", "depends_on", "lifecycle",
                         "description", "name", "comment"})


# ==================================================================
# 変換本体
# ==================================================================

def convert(root_dir: Path, state_ids: set[str] | None):
    notes: list[str] = []
    called_dirs: set[str] = set()
    blocks = load_module(root_dir, "", (), notes, called_dirs)
    defaults = var_defaults(blocks)
    resources = [b for b in blocks if b.btype == "resource" and len(b.labels) > 1]
    by_id = {rid(b): b for b in resources}

    # --- 未参照ローカルモジュール(source ディレクトリ実体で突合) ---
    for md in sorted(root_dir.glob("modules/*")):
        if md.is_dir() and any(md.glob("*.tf")) \
                and str(md.resolve()) not in called_dirs:
            notes.append(f"未参照モジュール: modules/{md.name}"
                         "(定義のみ・どこからも呼ばれていない)")

    # --- 間接参照の解決表(local 代入・module 出力・module 入力 var) ---
    locals_map: dict[tuple, str] = {}
    for b in blocks:
        if b.btype == "locals":
            for k, v in b.attrs.items():
                locals_map[(b.prefix, k)] = v
    outputs_map: dict[str, tuple[str, str]] = {}
    for b in blocks:
        if b.btype == "output" and b.labels and b.prefix:
            owner = b.prefix.rstrip(".")
            outputs_map[f"module.{owner}.{b.labels[0]}"] = \
                (b.attrs.get("value") or "", b.prefix)
    module_calls = {b.labels[0]: b for b in blocks
                    if b.btype == "module" and b.labels}

    # --- 呼ばれているが出力をどこからも参照されないモジュール(レガシー疑い)---
    # 「未参照モジュール」(呼ばれてすらいない)とは別の罠: module ブロックは
    # あるが outputs を誰も使わない残骸が、稼働構成のノードとして無警告で
    # 混入していた。図に載せる価値の判断材料として注記する。
    used_modules: set[str] = set()
    for b2 in blocks:
        if b2.btype == "module":
            continue   # 呼び出しブロック自身の引数は出力参照ではない
        for r_ in all_refs(b2):
            if r_.startswith("module."):
                used_modules.add(r_.split(".")[1])
    for mname in module_calls:
        if "." in mname:   # ネスト呼び出しは呼び出し元モジュールの責務
            continue
        if mname not in used_modules:
            notes.append(f"モジュール {mname}: 出力がどこからも参照されて"
                         "いない(レガシー残骸の可能性 — 図に載せる価値を確認)")

    def resolve_refs(expr: str, prefix: str, depth: int = 0) -> list[str]:
        """式中の参照を最大 4 ホップ辿ってリソース id(rid)へ解決する。

        local 代入・module 出力・module 入力 var の間接参照に対応(env var
        エッジの黙った取りこぼしを防ぐ)。"""
        if depth > 4:
            return []
        out: list[str] = []
        for ref in refs_in(expr):
            head = ref.split(".")[0]
            if head == "local":
                lv = locals_map.get((prefix, ref.split(".", 1)[1]))
                if lv is not None:
                    out += resolve_refs(lv, prefix, depth + 1)
            elif head == "module":
                parts = ref.split(".")
                if len(parts) >= 3:
                    ov = outputs_map.get(
                        f"module.{prefix}{parts[1]}.{parts[2]}")
                    if ov is not None:
                        out += resolve_refs(ov[0], ov[1], depth + 1)
            elif head == "var":
                if prefix:  # モジュール入力: 呼び出し側の引数を辿る
                    call = module_calls.get(prefix.rstrip("."))
                    if call is not None:
                        arg = call.attrs.get(ref.split(".", 1)[1])
                        if arg is not None:
                            out += resolve_refs(arg, call.prefix, depth + 1)
            elif head == "data":
                continue
            else:
                t, _, nm = ref.partition(".")
                qual = f"{t}.{prefix}{nm}"
                if qual in by_id:
                    out.append(qual)
                elif ref in by_id:
                    out.append(ref)
        return out

    # --- コンテナ(VPC / サブネット) ---
    containers = []
    cont_ids: dict[str, str] = {}
    for b in resources:
        if b.labels[0] == "aws_vpc":
            cid = sid(b.labels[1])
            cont_ids[rid(b)] = cid
            containers.append({"id": cid, "label": f"VPC ({b.labels[1]})",
                               "type": "vpc", "parent": "cloud"})
    for b in resources:
        if b.labels[0] != "aws_subnet":
            continue
        cid = sid(b.labels[1])
        cont_ids[rid(b)] = cid
        public = ("map_public_ip_on_launch" in b.attrs
                  and "true" in b.attrs["map_public_ip_on_launch"]) \
            or "public" in b.labels[1].lower()
        vpc_rids = resolve_refs(b.attrs.get("vpc_id", ""), b.prefix)
        containers.append({
            "id": cid, "label": b.labels[1],
            "type": "public_subnet" if public else "private_subnet",
            "parent": next((cont_ids[v] for v in vpc_rids
                            if v in cont_ids), "cloud")})

    # サブネットグループ → 先頭サブネットの対応(multi-AZ は片側へ代表化)
    group_subnet: dict[str, str] = {}
    for b in resources:
        if b.labels[0] in ("aws_db_subnet_group",
                           "aws_elasticache_subnet_group"):
            subs = [r for r in resolve_refs(
                        b.attrs.get("subnet_ids", ""), b.prefix)
                    if r.startswith("aws_subnet.")]
            if subs:
                group_subnet[rid(b)] = subs[0]

    def placement(b: Block) -> str:
        """所属コンテナを構造化属性(subnet/vpc/グループ)から決める。
        tags 等の無関係な言及では動かない。サブネット > グループ > VPC。"""
        subs: list[str] = []
        vpcs: list[str] = []
        groups: list[str] = []

        def scan(blk: Block):
            for k, v in blk.attrs.items():
                if k in SUBNET_ATTRS:
                    subs.extend(resolve_refs(v, b.prefix))
                elif k in VPC_ATTRS:
                    vpcs.extend(resolve_refs(v, b.prefix))
                elif k in GROUP_ATTRS:
                    groups.extend(resolve_refs(v, b.prefix))
            for c in blk.blocks:
                scan(c)
        scan(b)
        for s_ in subs:
            if s_ in cont_ids:
                return cont_ids[s_]
        for g_ in groups:
            s_ = group_subnet.get(g_)
            if s_ in cont_ids:
                return cont_ids[s_]
        for v_ in vpcs:
            if v_ in cont_ids:
                return cont_ids[v_]
        return "cloud"

    # --- ノード ---
    nodes = []
    node_ids: dict[str, str] = {}
    multi_ids: dict[str, dict[str, str]] = {}   # for_each 展開: rid → {key: nid}
    review_unmapped = []
    dead_notes = []
    taken: set[str] = set()

    def alloc_nid(base: str, short: str) -> str:
        nid = sid(base)
        if nid in taken:
            nid = sid(f"{base}_{short}")
        k2 = 2
        while nid in taken:
            nid = sid(f"{base}_{short}{k2}")
            k2 += 1
        taken.add(nid)
        return nid

    for b in resources:
        rtype, name = b.labels[0], b.labels[1]
        if rtype in CONTAINER_TYPES:
            continue
        dn = count_note(b, defaults)
        icon = NODE_ICONS.get(rtype)
        if icon is None:
            if not is_plumbing(rtype):
                review_unmapped.append(f"{rtype}.{name}")
            continue
        if state_ids is not None and rid(b) not in state_ids and dn is None:
            dead_notes.append(f"{rid(b)}: state に存在しない(未適用/削除済み)")
        short = rtype.removeprefix("aws_").split("_")[0]
        parent = placement(b)
        fentries = (foreach_entries(b, locals_map)
                    if "for_each" in b.attrs else None)
        if fentries and len(fentries) >= 2:
            # for_each をインスタンスごとのノードに展開(黙った縮約をしない)
            inst: dict[str, str] = {}
            for key in fentries:
                nid = alloc_nid(f"{name}_{key}", short)
                node = {"id": nid,
                        "label": (f'{name}["{key}"]\n'
                                  f"({rtype.removeprefix('aws_')})"),
                        "icon": icon, "parent": parent}
                if dn:
                    node["style_extra"] = "opacity=50;"
                    node["label"] += "\n[条件付き]"
                nodes.append(node)
                inst[key] = nid
            multi_ids[rid(b)] = inst
            dead_notes.append(f"{rid(b)}: for_each を {len(fentries)} "
                              f"インスタンスに展開({', '.join(fentries)})")
            if dn:
                dead_notes.append(f"{rid(b)}: {dn}")
            continue
        if "for_each" in b.attrs and not fentries:
            dead_notes.append(f"{rid(b)}: for_each のキーを静的解決できず "
                              "1 ノードに縮約 — インスタンス数を .tf で確認し、"
                              "必要なら手で展開する")
        nid = alloc_nid(name, short)
        node_ids[rid(b)] = nid
        node = {"id": nid, "label": f"{name}\n({rtype.removeprefix('aws_')})",
                "icon": icon, "parent": parent}
        if dn:
            dead_notes.append(f"{rid(b)}: {dn}")
            node["style_extra"] = "opacity=50;"
            node["label"] += "\n[条件付き]"
        nodes.append(node)

    # --- エッジ ---
    edges: dict[tuple, dict] = {}
    candidates: list[dict] = []

    IDX_RE = re.compile(
        r"\b((?:aws|random|null|archive|local|time|tls)_[a-z0-9_]+"
        r"\.[\w-]+)\[\s*\"([\w-]+)\"\s*\]")

    def indexed_keys(expr: str, prefix: str) -> dict[str, str]:
        """`aws_lambda_function.fn["transform"]` 形式のインスタンス指定を拾う
        (for_each 展開ノードへエッジをピンポイントで張るため)。"""
        out: dict[str, str] = {}
        for m in IDX_RE.finditer(expr or ""):
            t, _, nm = m.group(1).partition(".")
            qual = f"{t}.{prefix}{nm}"
            out[qual if qual in by_id else m.group(1)] = m.group(2)
        return out

    def add_edge(src_rid, dst_rid, kind, reason, confirmed,
                 src_key=None, dst_key=None):
        def nids(r, key):
            if r in node_ids:
                return [node_ids[r]]
            mi = multi_ids.get(r)
            if mi:   # for_each 展開: キー指定はそのインスタンス、無指定は全部
                if key is not None and key in mi:
                    return [mi[key]]
                return list(mi.values())
            c = cont_ids.get(r)
            return [c] if c else []
        for s in nids(src_rid, src_key):
            for d in nids(dst_rid, dst_key):
                if s == d:
                    continue
                item = {"src": s, "dst": d, "kind": kind, "reason": reason}
                if confirmed:
                    edges.setdefault((s, d), item)
                else:
                    candidates.append({**item, "confidence": reason})

    for b in resources:
        rtype = b.labels[0]
        pfx = b.prefix
        if rtype == "aws_lambda_event_source_mapping":
            ikeys = indexed_keys(b.attrs.get("event_source_arn", "") + " "
                                 + b.attrs.get("function_name", ""), pfx)
            for s_ in resolve_refs(b.attrs.get("event_source_arn", ""), pfx):
                for f_ in resolve_refs(b.attrs.get("function_name", ""), pfx):
                    if f_.startswith("aws_lambda_function."):
                        add_edge(s_, f_, "sub", "event_source_mapping", True,
                                 src_key=ikeys.get(s_), dst_key=ikeys.get(f_))
        elif rtype == "aws_sns_topic_subscription":
            for t_ in resolve_refs(b.attrs.get("topic_arn", ""), pfx):
                for d_ in resolve_refs(b.attrs.get("endpoint", ""), pfx):
                    add_edge(t_, d_, "sub", "sns_subscription", True)
        elif rtype == "aws_cloudwatch_event_target":
            for r_ in resolve_refs(b.attrs.get("rule", ""), pfx):
                for d_ in resolve_refs(b.attrs.get("arn", ""), pfx):
                    add_edge(r_, d_, "sub", "event_target", True)
        elif rtype == "aws_s3_bucket_notification":
            buckets = resolve_refs(b.attrs.get("bucket", ""), pfx)
            dsts = [d_ for d_ in set(resolve_refs(
                        json.dumps(b.attrs, ensure_ascii=False), pfx))
                    if d_.startswith(("aws_lambda_function.",
                                      "aws_sqs_queue.", "aws_sns_topic."))]
            for b_ in buckets:
                for d_ in dsts:
                    add_edge(b_, d_, "sub", "s3_notification", True)
        elif rtype in ("aws_apigatewayv2_integration",
                       "aws_api_gateway_integration"):
            whole = json.dumps({**b.attrs,
                                "_": [a.attrs for a in b.blocks]},
                               ensure_ascii=False)
            rids = resolve_refs(whole, pfx)
            apis = [r for r in rids
                    if r.startswith(("aws_apigatewayv2_api.",
                                     "aws_api_gateway_rest_api."))]
            fns = [r for r in rids if r.startswith("aws_lambda_function.")]
            for a_ in apis:
                for f_ in fns:
                    add_edge(a_, f_, "main", "apigw_integration", True)

    # env var 参照(強い証拠。local/module 出力の間接参照も解決)
    lambda_review = []
    for b in resources:
        if b.labels[0] != "aws_lambda_function":
            continue
        me = rid(b)
        pairs: list[tuple[str, str]] = []
        for envb in b.find("environment"):
            vexpr = envb.attrs.get("variables", "")
            for m in re.finditer(r'(\w+)\s*=\s*("[^"]*"|[^\n,{}]+)', vexpr):
                pairs.append((m.group(1), m.group(2)))
            for vb in envb.find("variables"):
                pairs.extend(vb.attrs.items())
        for k, v in pairs:
            for r_ in resolve_refs(v, b.prefix):
                tgt = by_id.get(r_)
                kind = "sub" if tgt is not None and any(
                    h in tgt.labels[0] for h in ASYNC_HINTS) else "main"
                add_edge(me, r_, kind, f"env:{k}", True,
                         dst_key=indexed_keys(v, b.prefix).get(r_))
        hints = []
        for key in ("filename", "s3_key", "image_uri", "handler", "runtime"):
            if key in b.attrs:
                hints.append(f"{key}={b.attrs[key][:80]}")
        for s_ in refs_in(b.attrs.get("filename", "")):
            if s_.startswith("data.archive_file."):
                hints.append(f"archive={s_}")
        inst_map = multi_ids.get(me)
        if inst_map:   # for_each 展開: インスタンスごとに each.* を実値化
            fentries = foreach_entries(b, locals_map) or {}
            for key_, nid_ in inst_map.items():
                hints_i = [subst_each(h, key_, fentries.get(key_, ""))
                           for h in hints]
                hints_i.append(f"for_each_key={key_}")
                lambda_review.append({"node": nid_, "hints": hints_i,
                                      "_dir": str(Path(b.path).parent)})
        else:
            lambda_review.append({"node": node_ids.get(me, sid(me)),
                                  "hints": hints,
                                  "_dir": str(Path(b.path).parent)})

    # archive_file の source_dir をヒントに合流(実パスに解決)
    arch_dirs = {}
    for b in blocks:
        if b.btype == "data" and b.labels[:1] == ["archive_file"]:
            arch_dirs[f"data.archive_file.{b.labels[1]}"] = \
                (b.attrs.get("source_dir") or b.attrs.get("source_file") or "")
    for item in lambda_review:
        mdir = item.pop("_dir", str(root_dir))
        resolved = []
        has_source = False
        for h in item["hints"]:
            if h.startswith("archive="):
                raw_src = arch_dirs.get(h[8:], "").strip().strip('"')
                real = raw_src.replace("${path.module}", mdir)
                if real:
                    resolved.append(f"source={real}")
                    has_source = True
                continue
            if h.startswith("filename=") and "${path.module}" in h:
                h = h.replace("${path.module}", mdir)
            if h.startswith("filename="):
                # filename がリポジトリ内の実在パスなら source= に昇格する
                # (従来は「ソースなし」と誤案内し、エージェントが二度手間)
                cand = h[len("filename="):].strip().strip('"')
                p_ = Path(cand) if Path(cand).is_absolute() else Path(mdir) / cand
                if cand and not re.search(r"[${]", cand) and p_.exists():
                    resolved.append(f"source={p_}")
                    has_source = True
                    continue
            resolved.append(h)
        if not has_source:
            resolved.append("code=リポジトリ内にソースなし(ビルド済み"
                            "アーティファクト参照)— env/トリガー/IAM のみで判断")
        item["hints"] = resolved

    # IAM ポリシー由来の候補
    for b in resources:
        if not b.labels[0].startswith("aws_iam_role_policy"):
            continue
        whole = json.dumps(b.attrs, ensure_ascii=False)
        actions = re.findall(r'"(\w+):[A-Za-z*]+"', whole)
        touched = [r for r in resolve_refs(whole, b.prefix)
                   if r.split(".")[0] in
                   ("aws_dynamodb_table", "aws_s3_bucket", "aws_sqs_queue",
                    "aws_sns_topic", "aws_kinesis_stream")]
        holders = [r for r in resolve_refs(b.attrs.get("role", "") or whole,
                                           b.prefix)
                   if r.startswith("aws_iam_role.")]
        for role in holders:
            for rb in resources:
                if rid(rb) not in node_ids:
                    continue
                if role in resolve_refs(rb.attrs.get("role", ""), rb.prefix):
                    for t in touched:
                        candidates.append({
                            "src": node_ids[rid(rb)],
                            "dst": node_ids.get(t) or cont_ids.get(t),
                            "kind": "main",
                            "confidence":
                            f"iam:{','.join(sorted(set(actions))[:3])}"})

    # 汎用参照(低確度候補)。tags/lifecycle 等の非通信属性は見ない
    for b in resources:
        me = rid(b)
        if me not in node_ids:
            continue
        signal = {k: v for k, v in b.attrs.items() if k not in NOISE_ATTRS}
        whole = json.dumps({**signal, "_": [a.attrs for a in b.blocks
                                            if a.btype not in NOISE_ATTRS]},
                           ensure_ascii=False)
        for r_ in set(resolve_refs(whole, b.prefix)):
            if r_ in node_ids and r_ != me:
                candidates.append({"src": node_ids[me], "dst": node_ids[r_],
                                   "kind": "main", "confidence": "attr_ref"})

    # 候補から確定済みを除去・重複排除
    seen_c = set(edges)
    uniq = []
    for c in candidates:
        if not c.get("src") or not c.get("dst") or c["src"] == c["dst"]:
            continue
        k = (c["src"], c["dst"])
        if k in seen_c or (k[1], k[0]) in edges:
            continue
        seen_c.add(k)
        uniq.append(c)

    # 空コンテナの剪定(multi-AZ の余りサブネット等はビルドが die するため)
    node_parents = {n["parent"] for n in nodes}
    while True:
        with_children = set(node_parents) | {c["parent"] for c in containers}
        removed = [c for c in containers if c["id"] not in with_children]
        if not removed:
            break
        for c in removed:
            notes.append(f"空コンテナを省略: {c['id']}(子ノードなし。"
                         "multi-AZ の対サブネットは片側に代表化)")
        containers = [c for c in containers if c["id"] in with_children]

    spec = {
        "name": root_dir.resolve().name,
        "meta": {
            "purpose": "(要記入: 何を伝える図か)",
            "audience": "(要記入)",
            "scope": f"Terraform root: {root_dir.resolve().name}",
            "abstraction": "概要",
            "assumptions": "情報源: .tf 静的解析(tf_to_spec)。"
                           "エッジ候補と Lambda コードは review 参照",
        },
        "legend": {"main": "同期呼び出し", "sub": "非同期・イベント"},
        "containers": [{"id": "cloud", "label": "AWS Cloud",
                        "type": "aws_cloud"}] + containers,
        "nodes": nodes,
        "edges": [dict(v, id=f"e{i}") for i, (k, v) in
                  enumerate(sorted(edges.items()))],
    }
    for e in spec["edges"]:
        e.pop("reason", None)
    review = {
        "confirmed_edges": [{"src": v["src"], "dst": v["dst"],
                             "reason": v.get("reason", "")}
                            for v in edges.values()],
        "edge_candidates": uniq,
        "lambda_code_review": lambda_review,
        "unmapped_resources": review_unmapped,
        "notes": dead_notes + notes,
    }
    return spec, review


def load_state_ids(path: Path) -> set[str]:
    """state(pull 生 JSON / show -json)からリソースアドレス集合だけ抽出。
    sensitive 値・attributes は一切読まない。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    ids = set()
    if "resources" in data:                     # state pull 形式
        for r in data.get("resources", []):
            if r.get("mode") == "managed":
                ids.add(f"{r.get('type')}.{r.get('name')}")
    def walk(mod):                              # show -json 形式
        for r in mod.get("resources", []):
            addr = r.get("address", "")
            ids.add(re.sub(r"^(?:module\.[^.]+\.)+", "", addr))
        for c in mod.get("child_modules", []):
            walk(c)
    walk(data.get("values", {}).get("root_module", {}))
    return ids


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    root = Path(args[0])
    if not root.is_dir() or not any(root.glob("*.tf")):
        print(f"ERROR: {root} に .tf がありません(root module の"
              "ディレクトリを指定。envs/ 分割の場合はどの環境かをユーザーに確認)")
        return 1
    out = review_out = None
    state_ids = None
    i = 1
    while i < len(args):
        if args[i] == "-o" and i + 1 < len(args):
            out = Path(args[i + 1]); i += 2
        elif args[i] == "--review" and i + 1 < len(args):
            review_out = Path(args[i + 1]); i += 2
        elif args[i] == "--state" and i + 1 < len(args):
            try:
                state_ids = load_state_ids(Path(args[i + 1]))
            except Exception as e:
                print(f"ERROR: state を読めません({e.__class__.__name__})。"
                      "terraform state pull か terraform show -json の出力を"
                      "そのまま渡してください")
                return 1
            i += 2
        else:
            print(f"ERROR: 不明な引数 {args[i]}"); return 1
    spec, review = convert(root, state_ids)
    out = out or Path(f"{spec['name']}.spec.json")
    review_out = review_out or out.with_suffix("").with_suffix("") \
        .parent / (out.name.replace(".spec.json", "") + ".review.json")
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    review_out.write_text(json.dumps(review, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    n_cand = len(review["edge_candidates"])
    print(f"スペック骨格: {out}(ノード {len(spec['nodes'])}・コンテナ "
          f"{len(spec['containers'])}・確定エッジ {len(spec['edges'])})")
    print(f"レビュー情報: {review_out}(エッジ候補 {n_cand}・Lambda 確認 "
          f"{len(review['lambda_code_review'])}・未対応型 "
          f"{len(review['unmapped_resources'])}・注記 {len(review['notes'])})")
    print("次の手順: ①review の Lambda ソースを読んでエッジを確定 "
          "②候補を採用/棄却 ③build_drawio.py --optimize 30 で叩き台生成")
    return 0


if __name__ == "__main__":
    sys.exit(main())

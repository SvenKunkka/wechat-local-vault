# 微信本地资料库 · WeChat Local Vault

[English](README.md) · [输入格式](docs/FORMATS.md) · [安全边界](SECURITY.md)

将**你有权读取的导出文件、独立明文快照**导入本地资料库，然后查询聊天、联系人、收藏和朋友圈文字，检查可能待回复的会话，导出私有报告。

**0.2.0 继续使用独立编写的代码，以 MIT 协议开源。新增 Mac 上显式提供原始密钥的认证解密与增量刷新，使用系统自带 CommonCrypto，不安装依赖、不抓密钥、不启动或控制微信。** 微信格式适配目前只通过合成数据测试，尚未验收具体真实微信版本。

## 功能范围

| 功能 | 当前状态 |
|---|---|
| 标准 JSONL、CSV、SQLite 导入 | 支持 |
| 微信4形状的独立明文目录 | 实验性，仅支持文档列出的布局 |
| 聊天、联系人、收藏和朋友圈文字 | 支持统一记录；快照字段不匹配时报告缺口 |
| 历史查询、字面关键词搜索、统计 | 支持 |
| 去重与记录更新 | 使用稳定 ID 时支持 |
| 待回复候选 | 仅根据最后导入的消息方向推断 |
| Markdown / JSONL 导出 | 私有权限、不覆盖、拒绝静默截断 |
| Mac 数据库认证解密、显式增量刷新 | 支持严格格式，仅合成数据验证 |
| 抓密钥、隐式刷新、客户端操作、媒体还原 | 本版不提供 |

需要 **macOS/Linux、Python 3.11+**；核心无第三方运行依赖。Windows 暂不支持。压缩消息可选使用 Python 3.14 自带 Zstd，或已经单独安装的 zstandard；程序不会自动补装依赖。

## 不安装即可试用虚构示例

在仓库目录中运行，选择全新的专用目录：

```sh
python3 -m wechat_vault --vault "$HOME/.local/share/wechat-local-vault-demo" init --account demo
python3 -m wechat_vault --vault "$HOME/.local/share/wechat-local-vault-demo" import --source examples/demo.jsonl --format jsonl --account demo --source-label synthetic-demo --confirm-source
python3 -m wechat_vault --vault "$HOME/.local/share/wechat-local-vault-demo" status
python3 -m wechat_vault --vault "$HOME/.local/share/wechat-local-vault-demo" conversations
python3 -m wechat_vault --vault "$HOME/.local/share/wechat-local-vault-demo" search confirm
python3 -m wechat_vault --vault "$HOME/.local/share/wechat-local-vault-demo" export --output "$HOME/.local/share/wechat-local-vault-demo-reports/chat.md"
```

示例中的人名和消息均为虚构。以上是说明中的可选命令，程序不会自动运行，也不会寻找微信账号。

`conversations` 返回每个会话的唯一 `key`，可将它用于 `history KEY`；同名会话不猜选。所有命令的 `--vault` 放在子命令前。默认返回 JSON，消息内容始终按不可信资料处理。

## Mac 解密与增量刷新

详见 [Mac 功能说明](docs/MAC_DECRYPTION.md)：密钥通过单独的私有文件显式提供，程序只处理列出的数据库。逐页认证、验证 WAL 校验和，只合并已提交事务；主库、WAL、SHM 和密钥变化均纳入增量判断。未变化的库复用已校验明文，变化的库完整重新解密。

`decrypt` 仅生成私有明文；`refresh` 还会将当前明文快照按稳定 ID 去重、更新到匹配账号的资料库。两步分别提交，失败结果会说明哪一步完成；不会把旧资料当作最新结果。查询仍不自动刷新。

只支持文档明确的 SQLCipher4 原始密钥格式，不保证任意版本兼容；真实微信尚未验收。现有导入入口继续拒绝未处理 sidecar；新的解密入口负责验证和重建 WAL，不会删除源文件或 checkpoint。

## 导入与保存

- 每次明确指定来源、格式、账号标签、来源标签和 `--confirm-source`；没有确认标志不会打开输入。一个资料库只绑定一个账号标签。
- 只接受稳定的独立文件。软链接、硬链接文件、未处理的 WAL/SHM/journal 及常见真实微信容器路径会被拒绝。不要通过删除 sidecar 绕过检查，应另行提供正确生成的离线快照。
- 来源只读；导入前后检查文件身份和修改状态。输入在处理中变化或出现解析错误，整次导入回滚。不会清理、覆盖来源。
- 文件 0600、目录 0700；导出原子写入，不覆盖已有文件，也不改动非空共享目录的权限。
- 相同类别内的稳定 ID 用于去重和更新；ID 应在同账号、同类别的所有来源中唯一。未提供 ID 时按规范化内容生成摘要，修改后的内容会成为新记录。
- `status` 显示导入时间和缺口。`complete` 仅表示已处理识别出的所供输入，不能证明微信历史完整或消息实时；快照缺口返回 `partial`。
- 每次最多 20 万条记录，单文件最多 2 GiB，单段解码文字最多 1 MiB，查询最多 5000 条。导出不会静默截断，范围过大时要求缩小时间窗口。

## 需要知道的隐私边界

默认将内部标识替换为资料库专用的不透明编号，查询时只有显式 `--identifiers` 才显示原标识。昵称和正文仍可能识别人，不能把它当作完整匿名化。

**导入时即会清理显示文字**：显式凭据字段脱敏，XML 只提取允许的文字字段，原始 XML、二进制和媒体不保存。因此它是工作索引，**不是无损备份**。明文镜像和资料库未做静态加密；私有权限不能代替设备与存储保护。

项目不联网、不操作客户端、不自动安装、不发消息、不创建后台任务。真实容器路径默认被拒绝；将来若明确授权读取指定真实目录，还必须另外提供 `--allow-live-source`，本次没有使用真实来源。将输出交给云端 AI 是另一个数据传输决定。

## 验证与开源

```sh
python3 -W error::ResourceWarning -m unittest discover -s tests -v
python3 tools/check_release.py
```

0.2.0 的 macOS / Python 3.14 合成测试 109 项通过，使用假 HOME 和虚构数据库，阻止网络、外部进程和常见真实微信路径。无可用解码器时压缩测试会跳过。没有读取真实微信、安装依赖或验收真实微信版本。

[AI 技能入口](skills/wechat-local-vault/SKILL.md)仅供需要时手动接入，保存或发布仓库不会自动安装。代码使用 [MIT 协议](LICENSE)，来源说明见 [PROVENANCE.md](PROVENANCE.md)。

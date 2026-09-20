# Reven 的 AppArmor 宿主配置

Ubuntu/Docker 默认 `docker-default` profile 禁止所有 mount；非特权 bubblewrap 必须在新 user/mount namespace 内建立临时根目录，因此仅允许 user namespaces 仍不足以运行沙箱。

`reven-self-host` 是只作用于 Reven 容器的命名 profile。它基于 [Moby v28.0.4 的默认模板](https://github.com/moby/moby/blob/v28.0.4/profiles/apparmor/template.go)，保留 `/proc`、`/sys`、signal、ptrace 的保护，将全局 mount 禁令替换为 bubblewrap 0.8 的限定临时挂载布局：`/tmp`、`/newroot`、`/oldroot`，以及必要的 tmpfs/devpts、bind/remount 和两次 pivot。其余未授权挂载仍默认拒绝。

这是对宿主默认 MAC 策略的局部适配；应用仍以 UID 10001 运行、根文件系统只读、丢弃全部 capabilities，并保留 no-new-privileges、seccomp、资源限制和现有恶意 fixture 测试。该文件不是通用容器 profile，不应套用于其他应用。当前验证基线为 Ubuntu 22.04 原生 AMD64；其他发行版与 AppArmor ABI 需要单独验证。

在启用 AppArmor 的 Docker 主机上安装一次，升级本文件时重复加载：

```bash
sudo install -m 0644 infra/self-host/apparmor/reven-self-host /etc/apparmor.d/reven-self-host
sudo apparmor_parser -r /etc/apparmor.d/reven-self-host
```

此后每次启动、升级、备份和恢复使用同一组 Compose 文件，加上 `-f infra/self-host/compose.apparmor.yml`。未启用 AppArmor 的宿主不使用该覆盖文件。不要使用 `privileged`、`apparmor=unconfined` 或修改全局 AppArmor/user namespace 开关来绕过失败。

原模板来源与许可：Moby v28.0.4，Apache-2.0；本目录保留固定版本的 [LICENSE](LICENSE) 与 [NOTICE](NOTICE) 原文。Reven 对模板的修改已在 profile 文件头标明。

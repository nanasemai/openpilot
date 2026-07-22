# 连接到 comma 3X 或 comma four

comma 设备是一台标准的 [Linux](https://github.com/commaai/agnos-builder) 计算机，提供 [SSH](https://wiki.archlinux.org/title/Secure_Shell) 和[串口控制台](https://wiki.archlinux.org/title/Working_with_the_serial_console)访问。

## 串口控制台

在 comma 3X 上，串口控制台可通过主 OBD-C 端口访问，经由 panda 转发。
使用 `panda/scripts/som_debug.sh` 进行连接。

comma four 也提供串口控制台，但需通过内部调试连接器访问。专用调试硬件即将在 comma 商店上架。

使用以下信息登录默认用户：

* 用户名：`comma`
* 密码：`comma`

## SSH

要通过 SSH 连接到你的设备，你需要一个已配置 SSH 密钥的 GitHub 账户。请参阅这篇 [GitHub 文章](https://docs.github.com/en/github/authenticating-to-github/connecting-to-github-with-ssh)了解如何为你的账户设置 SSH 密钥。

* 在设备设置中启用 SSH
* 在设备设置中输入你的 GitHub 用户名
* 连接到你的设备
    * 用户名：`comma`
    * 端口：`22`

以下是使用设备网络共享连接进行连接的示例命令：<br />
`ssh comma@192.168.43.1 -i ~/.ssh/my_github_key`

在设备上进行开发工作时，建议使用 [SSH agent forwarding](https://docs.github.com/en/developers/overview/using-ssh-agent-forwarding)。

## ADB

要使用 ADB 连接你的设备，请参考下图执行以下步骤：

![comma 3/3x 背面](../assets/three-back.svg)

* 将设备通过端口 2 连接到常供电电源，让设备启动
* 在设备设置中启用 ADB
* 通过端口 1 将设备连接到你的电脑
* 连接到你的设备
    * 通过 USB 使用 `adb shell`
    * 通过 WiFi 使用 `adb connect`
    * 以下是使用设备网络共享连接进行连接的示例命令：`adb connect 192.168.43.1:5555`

> [!NOTE]
> ADB 的默认端口是 5555。

更多关于 ADB 的信息，请参阅 [Android Debug Bridge (ADB) 文档](https://developer.android.com/tools/adb)。

### 说明

公钥仅从你的 GitHub 账户获取一次。如需更新设备的授权密钥，你需要重新输入你的 GitHub 用户名。

此目录中的 `id_rsa` 密钥仅在设备处于未安装软件的初始设置状态时有效。安装完成后，该默认密钥将被移除。

## ssh.comma.ai 代理

拥有 [comma prime 订阅](https://comma.ai/connect)后，你可以从任何地方通过 SSH 连接到你的 comma 设备。

使用以下 SSH 配置，你可以输入 `ssh comma-{设备ID}` 通过 `ssh.comma.ai` 连接到你的设备。

```
Host comma-*
  Port 22
  User comma
  IdentityFile ~/.ssh/my_github_key
  ProxyCommand ssh %h@ssh.comma.ai -W %h:%p

Host ssh.comma.ai
  Hostname ssh.comma.ai
  Port 22
  IdentityFile ~/.ssh/my_github_key
```

### 单次连接

```
ssh -i ~/.ssh/my_github_key -o ProxyCommand="ssh -i ~/.ssh/my_github_key -W %h:%p -p %p %h@ssh.comma.ai" comma@ffffffffffffffff
```

（将 `ffffffffffffffff` 替换为你的 dongle_id）

### ssh.comma.ai 主机密钥指纹

```
Host key fingerprint is SHA256:X22GOmfjGb9J04IA2+egtdaJ7vW9Fbtmpz9/x8/W1X4
+---[RSA 4096]----+
|                 |
|                 |
|        .        |
|         +   o   |
|        S = + +..|
|         + @ = .=|
|        . B @ ++=|
|         o * B XE|
|         .o o OB/|
+----[SHA256]-----+
```

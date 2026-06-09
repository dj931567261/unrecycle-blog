---
title: 如何安装与配置 OpenAI Codex CLI 和 Desktop App
slug: how-to-install-codex-cli-and-app
category: 开发工具
tags: OpenAI,Codex,CLI,Agent,Guide
summary: 这是一篇关于如何在 macOS, Linux 和 Windows 系统上安装、配置并使用 OpenAI Codex 命令行工具 (CLI) 与 Desktop 桌面客户端的详细指南。
is_published: true
---

# 如何安装与配置 OpenAI Codex CLI 和 Desktop App

在当下 AI 辅助编程日新月异的时代，OpenAI 的 **Codex** 已经演进为一个强大的 Agent 级编程助理。除了传统的网页端交互外，OpenAI 还提供了更加原生、高效的终端命令行工具 (**Codex CLI**) 以及桌面客户端 (**Codex Desktop App**)。

本篇文章将为您详细介绍如何在不同的操作系统上安装、登录并配置这些工具，帮助您打造流畅的 AI 编程工作流。

---

## 1. 安装 Codex CLI

Codex CLI 能够让您直接在终端中唤醒 AI，执行生成代码、解释代码、自动修复错误甚至管理本地项目等任务。

### 1.1 官方默认安装方式（适合可直连外网环境）

如果您的网络能够稳定访问 OpenAI 及 `chatgpt.com` 官方服务，可以使用官方的一键安装脚本。**注意**：官方的这套 Shell/PowerShell 脚本会直接下载编译好的独立二进制程序文件，**并不通过 npm 进行安装**。

#### macOS 和 Linux 安装
```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

#### Windows 安装
以管理员身份打开 PowerShell 窗口，执行以下命令：
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"
```

---

### 1.2 中国大陆用户推荐安装方式（通过 npm 镜像源）

由于网络环境限制，中国大陆用户直接使用 `curl` 下载官方脚本或二进制文件时极易遇到超时或连接失败的情况。**针对国内开发环境，最推荐且跨平台（macOS/Linux/Windows）的解决方案是使用 Node.js 的 `npm` 包管理器，配合国内镜像源进行安装。**

#### Step 1: 配置 npm 国内镜像源（以淘宝 NPM 镜像为例）
在您的终端（或 PowerShell）中运行以下命令，将 npm 源切换至国内镜像以确保下载顺畅：
```bash
npm config set registry https://registry.npmmirror.com
```

#### Step 2: 全局安装 Codex CLI
使用 npm 全局安装官方发布的 npm 包装包 `@openai/codex`：
```bash
npm install -g @openai/codex
```

> **提示**：安装完成后，您可以在终端中运行 `codex --version` 来验证是否安装成功。如果是在 macOS 或 Linux 系统下遇到权限报错，请在命令前加上 `sudo`（即 `sudo npm install -g @openai/codex`）。

---

## 2. 命令行登录与配置

安装完成后，您需要将 CLI 与您的 OpenAI 账户（需要包含相应的订阅计划，如 ChatGPT Plus, Pro, Business 或 Enterprise）进行关联。

### Step 1: 运行登录命令

在终端中执行：

```bash
codex login
```

### Step 2: 浏览器授权

终端会输出一个临时的授权 URL 或二维码，并自动在您的默认浏览器中打开登录页面。
1. 在网页端登录您的 OpenAI 账户。
2. 确认授权绑定本地 CLI 客户端。
3. 授权成功后，终端会显示 `Login successful!` 提示。

### Step 3: 验证安装

您可以运行以下命令检查版本，以确认安装与授权无误：

```bash
codex --version
```

---

## 3. 安装 Codex Desktop App (桌面客户端)

Codex Desktop App 提供了一个更加可视化的操作环境，支持屏幕取色、快捷键全局唤醒、多窗口管理，并能与主流的本地编辑器（如 VS Code、Cursor 等）无缝协作。

### 3.1 下载与安装
1. 访问官方入口 [chatgpt.com/codex](https://chatgpt.com/codex)。
2. 根据您的操作系统下载相应的安装包：
   - **macOS**：下载 `.dmg` 文件，拖拽至 `Applications` 文件夹即可。
   - **Windows**：下载 `.exe` 安装程序，双击运行并按照提示完成安装。
3. 安装完成后打开 Codex 应用，并使用您的账号登录。

### 3.2 启用本地编辑器集成
Codex 桌面端最具特色的功能之一就是能够直接操作系统上的代码编辑器。
* 打开 Codex App 的 **Settings (设置)**。
* 找到 **Editor Integrations (编辑器集成)**。
* 勾选您平时使用的编辑器（例如 Visual Studio Code）。这会在您的 VS Code 中自动配置 Codex 插件通道，使 AI 能够直接读取或重写您正在编辑的文件。

---

## 4. 快速上手使用

完成 CLI 与桌面端的安装后，您就可以尝试以下命令来感受 Codex 的高效了：

- **生成代码**：
  ```bash
  codex run "用 Python 写一个快速排序算法"
  ```
- **解释代码**：
  ```bash
  codex explain main.py
  ```
- **自动修复**：
  如果您的程序报错，可以直接把错误信息传给 Codex：
  ```bash
  codex fix "python run.py"
  ```

---

## 总结

通过配置 Codex CLI 和 Desktop App，您能够将 AI 深度嵌入到您的本地开发工作流中。无论是快速命令行交互，还是精细的代码编辑与项目重构，这些本地化工具都能为您带来质的飞跃。

如果您在安装过程中遇到任何问题，欢迎在下方留言讨论！

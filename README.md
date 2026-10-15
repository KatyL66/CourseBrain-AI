# CourseBrain

USC Brightspace 课程助手的 Private Beta 安装包。下载后在 Chrome 里加载，输入邀请码即可使用。不需要填写 OpenAI API Key。

## 下载

[coursebrain-extension-beta.zip](https://github.com/KatyL66/CourseBrain-AI/raw/main/coursebrain-extension-beta.zip)

## 安装

Chrome 不能直接安装 ZIP。

1. 下载上面的 ZIP 并解压。
2. 打开解压出来的文件夹，确认根目录里能直接看到 `manifest.json`。如果里面又套了一层文件夹，进入那一层，直到看到 `manifest.json`。
3. 打开 Chrome，在地址栏输入 `chrome://extensions`。
4. 打开右上角的「开发者模式」。
5. 点击「加载已解压的扩展程序」，选择含有 `manifest.json` 的那个文件夹。

## 使用

1. 登录 [Brightspace](https://brightspace.usc.edu)，打开一门课。
2. 点击地址栏右侧的拼图图标，再点击 CourseBrain。侧边栏会打开。需要的话可以把它固定在工具栏上。
3. 第一次使用时输入邀请码，点击「保存邀请码」。邀请码只保存在这台浏览器里。请向 CourseBrain 的维护者索取邀请码。
4. 在课程页面点击「同步当前 Brightspace 课程」。
5. 同步完成后直接提问。点击答案里的出处，会打开对应材料。

## 说明

- 只在 `https://brightspace.usc.edu` 上使用。
- 不需要、也不要填写 OpenAI Key。
- 每个邀请码每天的提问次数和同步次数有上限。

# 把速度变成蓝色
*openpilot 开发入门指南*

30 分钟内，我们将在您的电脑上搭建 openpilot 开发环境并对 openpilot 的 UI 做一些修改。

如果您有 comma four，我们还将把修改部署到您的设备上进行测试。

## 1. 设置开发环境

运行以下命令克隆 openpilot 并安装所有依赖：
```bash
bash <(curl -fsSL openpilot.comma.ai)
```

导航到 openpilot 文件夹并激活 Python 虚拟环境：
```bash
cd openpilot
source .venv/bin/activate
```

然后编译 openpilot：
```bash
scons
```

## 2. 运行回放

我们将使用演示路线运行 `replay` 工具，以获取用于测试 UI 更改的数据流。
```bash
# 在终端 1 中
tools/replay/replay --demo

# 在终端 2 中
./selfdrive/ui/ui.py
```

openpilot UI 应启动并显示演示路线的回放。

如果您有自己的 comma 设备，可以将 `--demo` 替换为您自己的路线（来自 comma connect）。

## 3. 把速度变成蓝色

现在让我们更新 UI 中的速度显示颜色。

搜索负责渲染当前速度的函数：
```bash
git grep "_draw_current_speed" selfdrive/ui/onroad/hud_renderer.py
```

您会在 `selfdrive/ui/onroad/hud_renderer.py` 中找到相关代码，位于此函数中：

```python
def _draw_current_speed(self, rect: rl.Rectangle) -> None:
  """绘制当前车辆速度和单位。"""
  speed_text = str(round(self.speed))
  speed_text_size = measure_text_cached(self._font_bold, speed_text, FONT_SIZES.current_speed)
  speed_pos = rl.Vector2(rect.x + rect.width / 2 - speed_text_size.x / 2, 180 - speed_text_size.y / 2)
  rl.draw_text_ex(self._font_bold, speed_text, speed_pos, FONT_SIZES.current_speed, 0, COLORS.white)  # <- 此行设置速度文字颜色
```

将 `COLORS.white` 改为**蓝色**。一个好看的柔和蓝色是 `#8080FF`，可以这样修改：

```diff
- rl.draw_text_ex(self._font_bold, speed_text, speed_pos, FONT_SIZES.current_speed, 0, COLORS.white)
+ rl.draw_text_ex(self._font_bold, speed_text, speed_pos, FONT_SIZES.current_speed, 0, rl.Color(0x80, 0x80, 0xFF, 255))
```

---

## 4. 重新运行 UI

修改后，重新运行 UI 查看效果：
```bash
./selfdrive/ui/ui.py
```
![](https://blog.comma.ai/img/blue_speed_ui.png)

现在您应该在演示回放中看到速度显示为漂亮的蓝色。

---

## 5. 推送到 GitHub

在 [Openpilot GitHub 仓库](https://github.com/commaai/openpilot)上点击 **"Fork"**。然后推送：
```bash
git remote rm origin
git remote add origin git@github.com:<您的-github-用户名>/openpilot.git
git add .
git commit -m "将速度显示改为蓝色"
git push --set-upstream origin master
```

---

## 6. 在您的 comma 设备上运行分支

通过设备上的设置卸载 Openpilot。

然后使用您自己的 GitHub 托管分支重新安装：
```
installer.comma.ai/<您的-github-用户名>/master
```

---

## 7. 在实车上欣赏您的成果 🚗💨

您已成功修改 Openpilot 的 UI 并将其部署到您自己的车辆上！

![](https://blog.comma.ai/img/c3_blue_ui.jpg)

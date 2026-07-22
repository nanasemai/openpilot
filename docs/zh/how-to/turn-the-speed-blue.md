# 将速度显示改为蓝色
*openpilot 开发入门指南*

30 分钟内，我们将在你的计算机上搭建好 openpilot 开发环境，并对 openpilot 的 UI 进行一些修改。

如果你有 comma four，我们还将把修改部署到你的设备上进行测试。

## 1. 搭建开发环境

运行以下命令来克隆 openpilot 并安装所有依赖：
```bash
bash <(curl -fsSL openpilot.comma.ai)
```

进入 openpilot 文件夹并激活 Python 虚拟环境：
```bash
cd openpilot
source .venv/bin/activate
```

然后，编译 openpilot：
```bash
scons
```

## 2. 运行回放

我们将使用 `replay` 工具配合演示路线来获取数据流，以便测试我们的 UI 修改。
```bash
# 在终端 1 中
tools/replay/replay --demo

# 在终端 2 中
./selfdrive/ui/ui.py
```

openpilot UI 将启动并显示演示路线的回放。

如果你有自己的 comma 设备，可以将 `--demo` 替换为你在 comma connect 上的某条路线。

## 3. 将速度显示改为蓝色

现在让我们更新 UI 中的速度显示颜色。

搜索负责渲染当前速度的函数：
```bash
git grep "_draw_current_speed" selfdrive/ui/onroad/hud_renderer.py
```

你会在 `selfdrive/ui/onroad/hud_renderer.py` 中找到相关代码，位于以下函数中：

```python
def _draw_current_speed(self, rect: rl.Rectangle) -> None:
  """绘制当前车辆速度及单位。"""
  speed_text = str(round(self.speed))
  speed_text_size = measure_text_cached(self._font_bold, speed_text, FONT_SIZES.current_speed)
  speed_pos = rl.Vector2(rect.x + rect.width / 2 - speed_text_size.x / 2, 180 - speed_text_size.y / 2)
  rl.draw_text_ex(self._font_bold, speed_text, speed_pos, FONT_SIZES.current_speed, 0, COLORS.white)  # <- 此行设置速度文字颜色
```

将 `COLORS.white` 改为**蓝色**。一种好看的柔和蓝色是 `#8080FF`，你可以直接内联修改：

```diff
- rl.draw_text_ex(self._font_bold, speed_text, speed_pos, FONT_SIZES.current_speed, 0, COLORS.white)
+ rl.draw_text_ex(self._font_bold, speed_text, speed_pos, FONT_SIZES.current_speed, 0, rl.Color(0x80, 0x80, 0xFF, 255))
```

---

## 4. 重新运行 UI

修改完成后，重新运行 UI 以查看新的界面：
```bash
./selfdrive/ui/ui.py
```
![](https://blog.comma.ai/img/blue_speed_ui.png)

现在你应该能在演示回放中看到速度显示为漂亮的蓝色了。

---

## 5. 将你的 Fork 推送到 GitHub

点击 [Openpilot GitHub 仓库](https://github.com/commaai/openpilot) 上的 **"Fork"** 按钮。然后推送：
```bash
git remote rm origin
git remote add origin git@github.com:<你的-github-用户名>/openpilot.git
git add .
git commit -m "将速度显示改为蓝色"
git push --set-upstream origin master
```

---

## 6. 在你的 comma 设备上运行你的 Fork

通过设备上的设置卸载 Openpilot。

然后使用你在 GitHub 上托管的 fork 重新安装：
```
installer.comma.ai/<你的-github-用户名>/master
```

---

## 7. 在实车上欣赏你的成果 🚗💨

现在你已经成功修改了 Openpilot 的 UI，并将其部署到了你自己的车上！

![](https://blog.comma.ai/img/c3_blue_ui.jpg)

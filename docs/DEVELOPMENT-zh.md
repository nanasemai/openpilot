# 文档开发

`docs/` 目录是 [docs.comma.ai](https://docs.comma.ai) 的源文件。
该网站通过此[工作流](../.github/workflows/docs.yaml)在推送到 master 分支时更新。

以下命令必须在 openpilot 的**根目录**下运行，**而不是 /docs**

**1. 安装文档依赖**
``` bash
uv pip install .[docs]
```

**2. 构建新站点**
``` bash
docs build
```

**3. 本地运行新站点**
``` bash
docs serve
```

参考资料：
* https://zensical.org/docs/

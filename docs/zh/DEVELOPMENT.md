# 文档开发

`docs/` 目录是 [docs.comma.ai](https://docs.comma.ai) 网站的源码来源。该站点在每次推送至 master 分支时通过此[工作流程](../.github/workflows/docs.yaml)自动更新。

以下命令必须在 openpilot 的根目录下运行，**而非 /docs 目录**。

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

参考文档：
* https://zensical.org/docs/

# Tabbit2API GitHub 同步指南

## 概述

本文档详细记录了将 Tabbit2API 项目同步到 GitHub 的完整过程。

## 操作步骤

### 1. 初始化 Git 仓库

首先在项目目录中初始化 Git 仓库：

```bash
cd /home/tabbit
git init
git config user.email "your_email@example.com"
git config user.name "Your Name"
```

**执行结果：**
```
Initialized empty Git repository in /home/tabbit/.git/
```

### 2. 创建 .gitignore 文件

创建 `.gitignore` 文件来忽略敏感文件和不必要的文件：

```bash
cat > .gitignore << 'EOF'
*.pyc
__pycache__/
*.pyo
*.pyd
.Python
.env
.env.local
.env.*.local
data/
config.json
Dockerfile.local
docker-compose.local.yml
logs/
*.log
.DS_Store
.idea/
.vscode/
*.egg-info/
.tox/
.coverage
htmlcov/
.pytest_cache/
EOF
```

**说明：**
- `config.json` - 包含 API Token 等敏感信息
- `data/` - 数据目录
- `__pycache__/` - Python 编译缓存
- `logs/` - 日志文件

### 3. 查看项目文件结构

```bash
find /home/tabbit -type f -name "*.py" -o -name "*.yml" -o -name "*.json" -o -name "*.sh" -o -name "*.md" -o -name "*.txt" -o -name "Dockerfile" | grep -v "__pycache__" | sort
```

**项目文件清单：**
```
/home/tabbit/core/config.py
/home/tabbit/core/tabbit_client.py
/home/tabbit/core/token_manager.py
/home/tabbit/core/log_manager.py
/home/tabbit/routes/openai_compat.py
/home/tabbit/routes/claude_compat.py
/home/tabbit/routes/admin.py
/home/tabbit/tabbit2api.py
/home/tabbit/requirements.txt
/home/tabbit/Dockerfile
/home/tabbit/docker-compose.yml
/home/tabbit/docker-entrypoint.sh
/home/tabbit/README.md
/home/tabbit/GITHUB_SYNC_GUIDE.md
```

### 4. 添加文件到暂存区

```bash
git add .gitignore
git add core/
git add routes/
git add tabbit2api.py
git add requirements.txt
git add Dockerfile
git add docker-compose.yml
git add docker-entrypoint.sh
git add README.md
git add GITHUB_SYNC_GUIDE.md
```

### 5. 查看暂存状态

```bash
git status
```

### 6. 提交代码

```bash
git commit -m "Initial commit - Tabbit2API project"
```

### 7. 在 GitHub 创建仓库

1. 打开 [GitHub](https://github.com)
2. 点击 "New repository"
3. 填写仓库信息：
   - Repository name: `tabbit2api`
   - Description: `Tabbit2API - Tabbit to OpenAI/Claude Compatible API`
   - Public/Private: 根据需求选择
   - 不要勾选 "Initialize this repository with a README"

### 8. 添加 GitHub 远程仓库

```bash
git remote add origin https://github.com/your_username/tabbit2api.git
```

**注意：** 请将 `your_username` 替换为你的 GitHub 用户名。

### 9. 推送到 GitHub

```bash
git branch -M main
git push -u origin main
```

## 后续维护

### 更新代码并推送

```bash
# 修改代码后
git add .
git commit -m "描述你的修改"
git push origin main
```

### 拉取远程更新

```bash
git pull origin main
```

### 查看提交历史

```bash
git log --oneline
```

## 重要提醒

1. **敏感信息保护**：确保 `config.json` 和 `data/` 目录不在版本控制中
2. **Token 管理**：API Token 应妥善保管，不要提交到 GitHub
3. **分支管理**：建议使用分支进行开发，合并到 main 分支前进行代码审查
4. **README 更新**：定期更新 README.md 文档

## 常见问题

### Q: 推送到 GitHub 时提示认证失败

**解决方案：**
- 使用 GitHub Personal Access Token 作为密码
- 在 GitHub 设置中创建 Token（Settings > Developer settings > Personal access tokens）
- 确保 Token 具有 `repo` 权限

### Q: 如何处理大型文件

**解决方案：**
- 使用 `.gitignore` 排除大型文件
- 考虑使用 Git LFS（Large File Storage）

### Q: 如何撤销提交

```bash
# 撤销最后一次提交（保留更改）
git reset --soft HEAD~1

# 撤销最后一次提交（丢弃更改）
git reset --hard HEAD~1
```

## 命令汇总

```bash
# 初始化
git init
git config user.email "your_email@example.com"
git config user.name "Your Name"

# 添加远程仓库
git remote add origin https://github.com/your_username/tabbit2api.git

# 日常操作
git status          # 查看状态
git add .           # 添加所有更改
git commit -m "msg" # 提交
git push origin main # 推送
git pull origin main # 拉取
```

---

**文档生成时间：** 2026-05-07
**项目版本：** Tabbit2API v1.0

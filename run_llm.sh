# 1. 安装 Ollama (如果尚未安装)
brew install ollama

# 2. 启动 Ollama 服务
ollama serve

# 3. 在一个新终端中，拉取并运行模型
ollama pull qwen3.5:9b-q4_K_M
ollama run qwen3.5:9b-q4_K_M
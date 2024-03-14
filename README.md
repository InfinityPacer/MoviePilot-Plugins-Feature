# MoviePilot-Plugins
MoviePilot三方插件：https://github.com/InfinityPacer/MoviePilot-Plugins

## 安装说明
MoviePilot环境变量添加本项目地址，具体参见 https://github.com/jxxghp/MoviePilot

## 插件说明

### 1. 站点刷流（低频版）
基于官方brushflow插件进行开发，相关调整
  - [x] 降低请求站点种子频率
  - [x] 优化某站UTC+0问题
  - [x] 支持删种排除MP标签
  - [x] 优化手工删种时更新统计的问题
  - [x] 支持种子筛选时支持种子副标题
  - [x] 支持种子筛选时自动过滤订阅内容标题
  - [x] 优化日志记录
  - [x] 重构刷流后台服务
  - [x] 支持没有勾选站点时能够继续刷流检查删种
  - [ ] 优化多站点刷流时随机站点刷流，避免多站点刷流时固定刷某站点，进一步降低无效的请求
  - [ ] 支持配置种子代理站点，解决下载器无法连接站点导致下载种子失败，无法获取Hash的问题
  - [ ] 支持部分规则按站点配置（如做种时间）
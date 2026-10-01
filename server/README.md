# 反馈接收服务部署

现状：代码与本地测试完成，公网未部署。最后更新：2026-10-01。

- 机器人链接只存本机开发凭据文件及服务器/etc/laoyu-sync-feedback.env，绝不进入Git/公开安装包。
- 部署目标沿用已有服务器111.231.25.152的HTTPS8443，不改DERP443、统计或其他服务。
- 安装代码到/opt/laoyu-sync-feedback/feedback_service.py，由独立laoyu-feedback用户运行；数据目录/var/lib/laoyu-sync-feedback权限0700。
- 环境文件root:root0600，字段LAOYU_FEEDBACK_WEBHOOK、LAOYU_FEEDBACK_BASE_URL=https://111.231.25.152:8443/sync-feedback、LAOYU_FEEDBACK_DATA=/var/lib/laoyu-sync-feedback。
- 安装laoyu-sync-feedback.service；将nginx-feedback.conf加入现有HTTPS server内，先备份线上原配置，nginx -t通过才reload，不能覆盖整个站点配置。
- 服务只监听127.0.0.1:18774；公网仅开放health、v1/submit与随机logs路径。关闭访问日志，不记录用户内容和密钥。
- 发布前实测HTTPS证书、反馈含版本/分类/留言/真实可下载ZIP链接、取消日志、错误机器人响应、过期链接、请求重复；验证后才把公开接收URL写入客户端并打包发布。
- 现有客户端feedback_url为空时需在新版迁移至可信发布配置；不可仅为开发机器填写地址，造成粉丝端仍未配置。

测试：python -m unittest discover -s server -p 'test_*.py' -v。5项测试使用临时目录和模拟机器人，不触及真实反馈；另有一次真实机器人连通测试（无用户数据），errcode=0。公网仍需SSH配置/凭据路径。

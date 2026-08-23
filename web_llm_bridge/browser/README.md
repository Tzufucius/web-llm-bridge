# Browser

`BrowserLauncher` 通过系统浏览器可执行文件打开目标 URL，使用用户现有的浏览器 profile。
它不检测或复用浏览器进程、不创建临时 profile，也不负责终止浏览器。

`BrowserBootstrap` 先启动 Extension WebSocket transport，等待 2 秒宽限期；仍未握手时拉起浏览器，再等待扩展握手，默认握手超时为 60 秒。
握手失败会抛出带稳定错误码的 `RPCError`，浏览器启动失败会抛出 `BrowserLaunchError`。

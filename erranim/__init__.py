"""ERROR-animation —— 模拟恐怖风格的终端艺术。

素材：Windows 服务控制管理器（SCM）崩溃日志。
架构：Scene（时间的纯函数）-> Grid（宽字符网格）-> Emitter（ANSI 差分输出）
     同一份 Grid 也可以落盘给 film.py 出片，终端版与视频版永远一致。
"""

__version__ = "0.1.0"

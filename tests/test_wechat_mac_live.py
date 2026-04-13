#!/usr/bin/env python3
"""
WeChat Mac 客户端通道实时测试

使用方法：
1. 确保微信已打开并登录
2. 打开微信的「文件传输助手」对话
3. 运行此脚本
4. 用手机向文件传输助手发送消息

注意：需要授予终端「辅助功能」权限
"""

import time
from pyclaw.channels import WeChatMacChannel


def main():
    print("=" * 50)
    print("WeChat Mac 客户端通道测试")
    print("=" * 50)

    # 创建通道
    channel = WeChatMacChannel(config={
        "poll_interval": 2.0,  # 每2秒检查一次
        "watch_contact": "文件传输助手"
    })

    # 设置消息回调
    def on_message(msg):
        print("\n" + "=" * 40)
        print(f"收到消息!")
        print(f"  来源: {msg.sender_name}")
        print(f"  内容: {msg.content}")
        print(f"  时间: {msg.timestamp}")
        print("=" * 40 + "\n")

        # 自动回复
        reply = f"收到: {msg.content[:20]}..."
        print(f"自动回复: {reply}")
        channel.send_to_filehelper(reply)

    channel.set_on_message(on_message)

    # 连接
    print("\n[1] 检查微信是否运行...")
    if not channel.connect():
        print("错误: 请先打开微信客户端")
        return

    print("[2] 微信已连接 ✓")

    # 打开文件传输助手
    print("[3] 正在打开文件传输助手...")
    channel.open_filehelper()
    time.sleep(1)

    # 发送测试消息
    print("[4] 发送测试消息...")
    channel.send_to_filehelper("PyClaw 已启动，等待消息...")

    # 开始监听
    print("[5] 开始监听消息...")
    print("\n" + "-" * 50)
    print("现在可以用手机向文件传输助手发送消息")
    print("按 Ctrl+C 退出")
    print("-" * 50 + "\n")

    channel.start_listening()

    # 保持运行
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在退出...")
        channel.stop_listening()
        channel.disconnect()
        print("已断开连接")


if __name__ == "__main__":
    main()

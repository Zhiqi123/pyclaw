"""
浏览器自动化工具 - 基于 Playwright

提供 Chrome/Firefox/Safari 浏览器的自动化控制。
"""

import asyncio
import base64
import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urljoin, urlparse

from .tools import Tool, ToolParameter, ToolRegistry

logger = logging.getLogger(__name__)

# 检查 Playwright 是否安装
try:
    from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    logger.warning("Playwright 未安装，浏览器自动化功能不可用。安装: pip install playwright && playwright install")


class BrowserManager:
    """
    浏览器管理器 - 单例模式

    管理浏览器实例的生命周期，避免频繁启动/关闭。
    """
    _instance = None
    _browser: Optional["Browser"] = None
    _context: Optional["BrowserContext"] = None
    _page: Optional["Page"] = None
    _playwright = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_page(self, headless: bool = True) -> "Page":
        """获取或创建页面"""
        if not HAS_PLAYWRIGHT:
            raise RuntimeError("Playwright 未安装")

        if self._page is None or self._page.is_closed():
            self._ensure_browser(headless)
            self._page = self._context.new_page()

        return self._page

    def _ensure_browser(self, headless: bool = True):
        """确保浏览器已启动"""
        if self._browser is None or not self._browser.is_connected():
            if self._playwright is None:
                self._playwright = sync_playwright().start()

            # 使用 Chromium，模拟真实用户
            self._browser = self._playwright.chromium.launch(
                headless=headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                ]
            )

            # 创建上下文，模拟真实浏览器
            self._context = self._browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                locale='zh-CN',
                timezone_id='Asia/Shanghai',
            )

            # 注入反检测脚本
            self._context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['zh-CN', 'zh', 'en']
                });
                window.chrome = { runtime: {} };
            """)

    def close(self):
        """关闭浏览器"""
        if self._page and not self._page.is_closed():
            self._page.close()
            self._page = None

        if self._context:
            self._context.close()
            self._context = None

        if self._browser:
            self._browser.close()
            self._browser = None

        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def new_page(self) -> "Page":
        """创建新标签页"""
        self._ensure_browser()
        return self._context.new_page()


# 全局浏览器管理器
_browser_manager: Optional[BrowserManager] = None


def _get_browser_manager() -> BrowserManager:
    """获取浏览器管理器"""
    global _browser_manager
    if _browser_manager is None:
        _browser_manager = BrowserManager()
    return _browser_manager


# ============================================================================
# 浏览器操作函数
# ============================================================================

def browser_open(
    url: str,
    headless: bool = True,
    wait_for: str = "load"
) -> Dict[str, Any]:
    """
    打开网页

    Args:
        url: 要打开的 URL
        headless: 是否无头模式（不显示浏览器窗口）
        wait_for: 等待条件 (load, domcontentloaded, networkidle)
    """
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright 未安装。安装: pip install playwright && playwright install", "success": False}

    try:
        manager = _get_browser_manager()
        page = manager.get_page(headless=headless)

        # 导航到页面
        response = page.goto(url, wait_until=wait_for, timeout=30000)

        return {
            "url": page.url,
            "title": page.title(),
            "status": response.status if response else None,
            "success": True
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_close() -> Dict[str, Any]:
    """关闭浏览器"""
    try:
        manager = _get_browser_manager()
        manager.close()
        return {"message": "浏览器已关闭", "success": True}
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_navigate(url: str, wait_for: str = "load") -> Dict[str, Any]:
    """
    导航到新 URL

    Args:
        url: 目标 URL
        wait_for: 等待条件
    """
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright 未安装", "success": False}

    try:
        manager = _get_browser_manager()
        page = manager.get_page()

        response = page.goto(url, wait_until=wait_for, timeout=30000)

        return {
            "url": page.url,
            "title": page.title(),
            "status": response.status if response else None,
            "success": True
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_back() -> Dict[str, Any]:
    """后退"""
    try:
        manager = _get_browser_manager()
        page = manager.get_page()
        page.go_back()
        return {"url": page.url, "title": page.title(), "success": True}
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_forward() -> Dict[str, Any]:
    """前进"""
    try:
        manager = _get_browser_manager()
        page = manager.get_page()
        page.go_forward()
        return {"url": page.url, "title": page.title(), "success": True}
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_refresh() -> Dict[str, Any]:
    """刷新页面"""
    try:
        manager = _get_browser_manager()
        page = manager.get_page()
        page.reload()
        return {"url": page.url, "title": page.title(), "success": True}
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_get_content(
    selector: Optional[str] = None,
    content_type: str = "text"
) -> Dict[str, Any]:
    """
    获取页面内容

    Args:
        selector: CSS 选择器，None 则获取整个页面
        content_type: 内容类型 (text, html, inner_text)
    """
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright 未安装", "success": False}

    try:
        manager = _get_browser_manager()
        page = manager.get_page()

        if selector:
            element = page.query_selector(selector)
            if not element:
                return {"error": f"找不到元素: {selector}", "success": False}

            if content_type == "html":
                content = element.inner_html()
            elif content_type == "inner_text":
                content = element.inner_text()
            else:
                content = element.text_content()
        else:
            if content_type == "html":
                content = page.content()
            else:
                content = page.inner_text("body")

        return {
            "content": content[:10000] if content else "",  # 限制长度
            "length": len(content) if content else 0,
            "url": page.url,
            "success": True
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_get_elements(
    selector: str,
    attributes: Optional[List[str]] = None,
    limit: int = 20
) -> Dict[str, Any]:
    """
    获取匹配的元素列表

    Args:
        selector: CSS 选择器
        attributes: 要获取的属性列表
        limit: 最大返回数量
    """
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright 未安装", "success": False}

    try:
        manager = _get_browser_manager()
        page = manager.get_page()

        elements = page.query_selector_all(selector)

        results = []
        for i, el in enumerate(elements[:limit]):
            item = {
                "index": i,
                "text": el.text_content()[:200] if el.text_content() else "",
                "tag": el.evaluate("el => el.tagName.toLowerCase()"),
            }

            # 获取指定属性
            if attributes:
                for attr in attributes:
                    item[attr] = el.get_attribute(attr)
            else:
                # 默认获取常用属性
                item["href"] = el.get_attribute("href")
                item["src"] = el.get_attribute("src")
                item["class"] = el.get_attribute("class")
                item["id"] = el.get_attribute("id")

            results.append(item)

        return {
            "elements": results,
            "count": len(results),
            "total": len(elements),
            "success": True
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_click(
    selector: str,
    index: int = 0,
    wait_after: int = 1000
) -> Dict[str, Any]:
    """
    点击元素

    Args:
        selector: CSS 选择器
        index: 如果有多个匹配元素，点击第几个（从0开始）
        wait_after: 点击后等待时间（毫秒）
    """
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright 未安装", "success": False}

    try:
        manager = _get_browser_manager()
        page = manager.get_page()

        elements = page.query_selector_all(selector)
        if not elements:
            return {"error": f"找不到元素: {selector}", "success": False}

        if index >= len(elements):
            return {"error": f"索引超出范围，共 {len(elements)} 个元素", "success": False}

        elements[index].click()

        if wait_after > 0:
            page.wait_for_timeout(wait_after)

        return {
            "message": f"已点击 {selector}",
            "url": page.url,
            "success": True
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_type(
    selector: str,
    text: str,
    clear: bool = True,
    press_enter: bool = False
) -> Dict[str, Any]:
    """
    在输入框中输入文字

    Args:
        selector: CSS 选择器
        text: 要输入的文字
        clear: 是否先清空
        press_enter: 输入后是否按回车
    """
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright 未安装", "success": False}

    try:
        manager = _get_browser_manager()
        page = manager.get_page()

        element = page.query_selector(selector)
        if not element:
            return {"error": f"找不到元素: {selector}", "success": False}

        if clear:
            element.fill("")

        element.type(text, delay=50)  # 模拟人类打字速度

        if press_enter:
            element.press("Enter")
            page.wait_for_timeout(1000)

        return {
            "message": f"已输入 {len(text)} 个字符",
            "url": page.url,
            "success": True
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_scroll(
    direction: str = "down",
    amount: int = 500,
    selector: Optional[str] = None
) -> Dict[str, Any]:
    """
    滚动页面

    Args:
        direction: 方向 (up, down, left, right, top, bottom)
        amount: 滚动量（像素）
        selector: 滚动特定元素（可选）
    """
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright 未安装", "success": False}

    try:
        manager = _get_browser_manager()
        page = manager.get_page()

        if direction == "top":
            page.evaluate("window.scrollTo(0, 0)")
        elif direction == "bottom":
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif direction == "down":
            page.evaluate(f"window.scrollBy(0, {amount})")
        elif direction == "up":
            page.evaluate(f"window.scrollBy(0, -{amount})")
        elif direction == "left":
            page.evaluate(f"window.scrollBy(-{amount}, 0)")
        elif direction == "right":
            page.evaluate(f"window.scrollBy({amount}, 0)")

        return {"message": f"已滚动 {direction}", "success": True}
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_screenshot(
    output_path: Optional[str] = None,
    selector: Optional[str] = None,
    full_page: bool = False
) -> Dict[str, Any]:
    """
    截取页面截图

    Args:
        output_path: 输出路径
        selector: 截取特定元素
        full_page: 是否截取整个页面
    """
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright 未安装", "success": False}

    try:
        manager = _get_browser_manager()
        page = manager.get_page()

        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.expanduser(f"~/Desktop/browser_{timestamp}.png")
        else:
            output_path = os.path.expanduser(output_path)

        if selector:
            element = page.query_selector(selector)
            if not element:
                return {"error": f"找不到元素: {selector}", "success": False}
            element.screenshot(path=output_path)
        else:
            page.screenshot(path=output_path, full_page=full_page)

        response = {
            "path": output_path,
            "url": page.url,
            "success": True
        }

        # 返回 base64（如果文件不太大）
        if os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            if file_size < 2 * 1024 * 1024:
                with open(output_path, "rb") as f:
                    response["base64"] = base64.b64encode(f.read()).decode()
                response["size"] = file_size

        return response
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_execute_js(script: str) -> Dict[str, Any]:
    """
    执行 JavaScript 代码

    Args:
        script: JavaScript 代码
    """
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright 未安装", "success": False}

    try:
        manager = _get_browser_manager()
        page = manager.get_page()

        result = page.evaluate(script)

        return {
            "result": result if result is not None else "undefined",
            "success": True
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_wait_for(
    selector: Optional[str] = None,
    state: str = "visible",
    timeout: int = 10000
) -> Dict[str, Any]:
    """
    等待元素或条件

    Args:
        selector: CSS 选择器
        state: 状态 (attached, detached, visible, hidden)
        timeout: 超时时间（毫秒）
    """
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright 未安装", "success": False}

    try:
        manager = _get_browser_manager()
        page = manager.get_page()

        if selector:
            page.wait_for_selector(selector, state=state, timeout=timeout)
            return {"message": f"元素 {selector} 已{state}", "success": True}
        else:
            page.wait_for_load_state("networkidle", timeout=timeout)
            return {"message": "页面加载完成", "success": True}
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_get_links(
    base_url: Optional[str] = None,
    filter_pattern: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取页面所有链接

    Args:
        base_url: 基础 URL（用于转换相对链接）
        filter_pattern: 过滤正则表达式
    """
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright 未安装", "success": False}

    try:
        manager = _get_browser_manager()
        page = manager.get_page()

        links = page.evaluate("""
            () => {
                const anchors = document.querySelectorAll('a[href]');
                return Array.from(anchors).map(a => ({
                    text: a.textContent?.trim().slice(0, 100) || '',
                    href: a.href,
                    target: a.target || ''
                }));
            }
        """)

        # 过滤
        if filter_pattern:
            pattern = re.compile(filter_pattern)
            links = [l for l in links if pattern.search(l["href"])]

        return {
            "links": links[:100],  # 限制数量
            "count": len(links),
            "success": True
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_get_images(download: bool = False) -> Dict[str, Any]:
    """
    获取页面所有图片

    Args:
        download: 是否下载图片
    """
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright 未安装", "success": False}

    try:
        manager = _get_browser_manager()
        page = manager.get_page()

        images = page.evaluate("""
            () => {
                const imgs = document.querySelectorAll('img');
                return Array.from(imgs).map(img => ({
                    src: img.src,
                    alt: img.alt || '',
                    width: img.naturalWidth,
                    height: img.naturalHeight
                }));
            }
        """)

        return {
            "images": images[:50],
            "count": len(images),
            "success": True
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_fill_form(
    fields: Dict[str, str],
    submit_selector: Optional[str] = None
) -> Dict[str, Any]:
    """
    填写表单

    Args:
        fields: 字段映射 {selector: value}
        submit_selector: 提交按钮选择器
    """
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright 未安装", "success": False}

    try:
        manager = _get_browser_manager()
        page = manager.get_page()

        filled = []
        for selector, value in fields.items():
            element = page.query_selector(selector)
            if element:
                tag = element.evaluate("el => el.tagName.toLowerCase()")

                if tag == "select":
                    element.select_option(value)
                elif tag == "input":
                    input_type = element.get_attribute("type") or "text"
                    if input_type in ("checkbox", "radio"):
                        if value.lower() in ("true", "1", "yes", "checked"):
                            element.check()
                    else:
                        element.fill(value)
                else:
                    element.fill(value)

                filled.append(selector)

        if submit_selector:
            page.click(submit_selector)
            page.wait_for_timeout(2000)

        return {
            "filled": filled,
            "count": len(filled),
            "url": page.url,
            "success": True
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_handle_dialog(action: str = "accept", text: Optional[str] = None) -> Dict[str, Any]:
    """
    处理对话框（alert/confirm/prompt）

    Args:
        action: 操作 (accept, dismiss)
        text: prompt 输入文字
    """
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright 未安装", "success": False}

    try:
        manager = _get_browser_manager()
        page = manager.get_page()

        def handle_dialog(dialog):
            if action == "accept":
                if text and dialog.type == "prompt":
                    dialog.accept(text)
                else:
                    dialog.accept()
            else:
                dialog.dismiss()

        page.on("dialog", handle_dialog)

        return {"message": f"对话框处理器已设置: {action}", "success": True}
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_get_cookies() -> Dict[str, Any]:
    """获取所有 cookies"""
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright 未安装", "success": False}

    try:
        manager = _get_browser_manager()
        page = manager.get_page()

        cookies = page.context.cookies()

        return {
            "cookies": cookies,
            "count": len(cookies),
            "success": True
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_set_cookies(cookies: List[Dict]) -> Dict[str, Any]:
    """
    设置 cookies

    Args:
        cookies: cookie 列表 [{name, value, domain, path, ...}]
    """
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright 未安装", "success": False}

    try:
        manager = _get_browser_manager()
        page = manager.get_page()

        page.context.add_cookies(cookies)

        return {"message": f"已设置 {len(cookies)} 个 cookies", "success": True}
    except Exception as e:
        return {"error": str(e), "success": False}


def browser_get_page_info() -> Dict[str, Any]:
    """获取当前页面信息"""
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright 未安装", "success": False}

    try:
        manager = _get_browser_manager()
        page = manager.get_page()

        info = page.evaluate("""
            () => ({
                url: window.location.href,
                title: document.title,
                domain: window.location.hostname,
                protocol: window.location.protocol,
                viewport: {
                    width: window.innerWidth,
                    height: window.innerHeight
                },
                scroll: {
                    x: window.scrollX,
                    y: window.scrollY,
                    maxY: document.body.scrollHeight - window.innerHeight
                },
                forms: document.forms.length,
                links: document.links.length,
                images: document.images.length
            })
        """)

        info["success"] = True
        return info
    except Exception as e:
        return {"error": str(e), "success": False}


# ============================================================================
# 注册浏览器工具
# ============================================================================

def register_browser_tools(registry: ToolRegistry) -> None:
    """注册浏览器自动化工具"""

    if not HAS_PLAYWRIGHT:
        logger.warning("Playwright 未安装，跳过浏览器工具注册")
        return

    # 打开浏览器
    registry.add(Tool(
        name="browser_open",
        description="打开浏览器并访问指定 URL。首次调用会启动浏览器。",
        parameters=[
            ToolParameter("url", "string", "要访问的 URL", required=True),
            ToolParameter("headless", "boolean", "是否无头模式（不显示窗口），默认 True"),
            ToolParameter("wait_for", "string", "等待条件", enum=["load", "domcontentloaded", "networkidle"]),
        ],
        handler=browser_open,
        category="browser"
    ))

    # 关闭浏览器
    registry.add(Tool(
        name="browser_close",
        description="关闭浏览器。",
        parameters=[],
        handler=browser_close,
        category="browser"
    ))

    # 导航
    registry.add(Tool(
        name="browser_navigate",
        description="导航到新的 URL。",
        parameters=[
            ToolParameter("url", "string", "目标 URL", required=True),
            ToolParameter("wait_for", "string", "等待条件"),
        ],
        handler=browser_navigate,
        category="browser"
    ))

    # 后退/前进/刷新
    registry.add(Tool(
        name="browser_back",
        description="浏览器后退。",
        parameters=[],
        handler=browser_back,
        category="browser"
    ))

    registry.add(Tool(
        name="browser_forward",
        description="浏览器前进。",
        parameters=[],
        handler=browser_forward,
        category="browser"
    ))

    registry.add(Tool(
        name="browser_refresh",
        description="刷新页面。",
        parameters=[],
        handler=browser_refresh,
        category="browser"
    ))

    # 获取内容
    registry.add(Tool(
        name="browser_get_content",
        description="获取页面文本或 HTML 内容。可以指定 CSS 选择器获取特定元素。",
        parameters=[
            ToolParameter("selector", "string", "CSS 选择器，不指定则获取整个页面"),
            ToolParameter("content_type", "string", "内容类型", enum=["text", "html", "inner_text"]),
        ],
        handler=browser_get_content,
        category="browser"
    ))

    # 获取元素列表
    registry.add(Tool(
        name="browser_get_elements",
        description="获取匹配 CSS 选择器的元素列表，返回文本和属性。",
        parameters=[
            ToolParameter("selector", "string", "CSS 选择器", required=True),
            ToolParameter("attributes", "array", "要获取的属性列表"),
            ToolParameter("limit", "number", "最大返回数量，默认 20"),
        ],
        handler=browser_get_elements,
        category="browser"
    ))

    # 点击
    registry.add(Tool(
        name="browser_click",
        description="点击页面元素。",
        parameters=[
            ToolParameter("selector", "string", "CSS 选择器", required=True),
            ToolParameter("index", "number", "元素索引（如果有多个匹配），从0开始"),
            ToolParameter("wait_after", "number", "点击后等待时间（毫秒）"),
        ],
        handler=browser_click,
        category="browser"
    ))

    # 输入
    registry.add(Tool(
        name="browser_type",
        description="在输入框中输入文字。模拟人类打字速度。",
        parameters=[
            ToolParameter("selector", "string", "CSS 选择器", required=True),
            ToolParameter("text", "string", "要输入的文字", required=True),
            ToolParameter("clear", "boolean", "是否先清空，默认 True"),
            ToolParameter("press_enter", "boolean", "输入后是否按回车"),
        ],
        handler=browser_type,
        category="browser"
    ))

    # 滚动
    registry.add(Tool(
        name="browser_scroll",
        description="滚动页面。",
        parameters=[
            ToolParameter("direction", "string", "方向", required=True, enum=["up", "down", "left", "right", "top", "bottom"]),
            ToolParameter("amount", "number", "滚动量（像素），默认 500"),
        ],
        handler=browser_scroll,
        category="browser"
    ))

    # 截图
    registry.add(Tool(
        name="browser_screenshot",
        description="截取页面截图。",
        parameters=[
            ToolParameter("output_path", "string", "输出路径（默认桌面）"),
            ToolParameter("selector", "string", "截取特定元素"),
            ToolParameter("full_page", "boolean", "是否截取整个页面"),
        ],
        handler=browser_screenshot,
        category="browser"
    ))

    # 执行 JS
    registry.add(Tool(
        name="browser_execute_js",
        description="在页面中执行 JavaScript 代码。",
        parameters=[
            ToolParameter("script", "string", "JavaScript 代码", required=True),
        ],
        handler=browser_execute_js,
        category="browser"
    ))

    # 等待
    registry.add(Tool(
        name="browser_wait_for",
        description="等待元素出现或页面加载完成。",
        parameters=[
            ToolParameter("selector", "string", "CSS 选择器"),
            ToolParameter("state", "string", "状态", enum=["attached", "detached", "visible", "hidden"]),
            ToolParameter("timeout", "number", "超时时间（毫秒），默认 10000"),
        ],
        handler=browser_wait_for,
        category="browser"
    ))

    # 获取链接
    registry.add(Tool(
        name="browser_get_links",
        description="获取页面所有链接。",
        parameters=[
            ToolParameter("filter_pattern", "string", "过滤正则表达式"),
        ],
        handler=browser_get_links,
        category="browser"
    ))

    # 获取图片
    registry.add(Tool(
        name="browser_get_images",
        description="获取页面所有图片信息。",
        parameters=[
            ToolParameter("download", "boolean", "是否下载图片"),
        ],
        handler=browser_get_images,
        category="browser"
    ))

    # 填写表单
    registry.add(Tool(
        name="browser_fill_form",
        description="批量填写表单字段。",
        parameters=[
            ToolParameter("fields", "object", "字段映射 {selector: value}", required=True),
            ToolParameter("submit_selector", "string", "提交按钮选择器"),
        ],
        handler=browser_fill_form,
        category="browser"
    ))

    # 获取页面信息
    registry.add(Tool(
        name="browser_get_page_info",
        description="获取当前页面的基本信息（URL、标题、viewport 等）。",
        parameters=[],
        handler=browser_get_page_info,
        category="browser"
    ))

    # Cookies
    registry.add(Tool(
        name="browser_get_cookies",
        description="获取当前页面的所有 cookies。",
        parameters=[],
        handler=browser_get_cookies,
        category="browser"
    ))

    registry.add(Tool(
        name="browser_set_cookies",
        description="设置 cookies。",
        parameters=[
            ToolParameter("cookies", "array", "cookie 列表", required=True),
        ],
        handler=browser_set_cookies,
        category="browser"
    ))

    logger.info(f"已注册浏览器工具，当前共 {len(registry.list_tools())} 个工具")

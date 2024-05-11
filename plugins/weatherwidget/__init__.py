from concurrent.futures import ThreadPoolExecutor
from concurrent.futures._base import as_completed
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Any, List, Dict, Tuple, Optional

from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from playwright.sync_api import sync_playwright
from starlette.responses import Response

SCREENSHOT_DEVICES = {
    "mobile": "iPhone 13 Pro Max",
    # "mobile_landscape": "iPhone 13 Pro Max landscape",
    "pc": "iPad Pro 11 landscape",
}


class WeatherWidget(_PluginBase):
    # region 全局定义

    # 插件名称
    plugin_name = "天气"
    # 插件描述
    plugin_desc = "仪表盘显示天气信息。"
    # 插件图标
    plugin_icon = "https://github.com/InfinityPacer/MoviePilot-Plugins/raw/main/icons/weather.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "InfinityPacer"
    # 作者主页
    author_url = "https://github.com/InfinityPacer"
    # 插件配置项ID前缀
    plugin_config_prefix = "weatherwidget_"
    # 加载顺序
    plugin_order = 1
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    # 启用
    # playwright
    _playwright = None
    # browser
    _browser = None
    # enable
    _enable = None
    # 退出事件
    _event = Event()
    _scheduler = None

    # endregion

    def init_plugin(self, config: dict = None):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.webkit.launch(headless=True)

        if not config:
            return

        self._enable = config.get("enable", False)

        self.__take_screenshots(location="shenzhen-101280601")

    def get_state(self) -> bool:
        return self._enable

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
            定义远程控制命令
            :return: 命令关键字、事件、描述、附带数据
            """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件API
        [{
            "path": "/xx",
            "endpoint": self.xxx,
            "methods": ["GET", "POST"],
            "summary": "API说明"
        }]
        """
        return [{
            "path": "/image",
            "endpoint": self.get_weather_image,
            "methods": ["GET"],
            "summary": "获取天气图片",
            "description": "获取天气图片",
        }]

    @staticmethod
    def __get_total_elements() -> List[dict]:
        """
        组装汇总元素
        """
        image_path = Path(f"{settings.CONFIG_PATH}/temp/iphone_pro_element_screenshot.png")

        return [{
            'component': 'VRow',
            'content': [
                {
                    'component': 'VCol',
                    'props': {
                        'cols': 12
                    },
                    'content': [
                        {
                            'component': 'VImg',
                            'props': {
                                'src': f'/api/v1/plugin/WeatherWidget/image?'
                                       f'path={image_path}&'
                                       f'apikey={settings.API_TOKEN}',
                                'height': 'auto',
                                'max-width': '100%'
                            }
                        }
                    ]
                }
            ]
        }]

    def get_dashboard(self) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
        """
        获取插件仪表盘页面，需要返回：1、仪表板col配置字典；2、全局配置（自动刷新等）；3、仪表板页面元素配置json（含数据）
        1、col配置参考：
        {
            "cols": 12, "md": 6
        }
        2、全局配置参考：
        {
            "refresh": 10 // 自动刷新时间，单位秒
        }
        3、页面配置使用Vuetify组件拼装，参考：https://vuetifyjs.com/
        """
        # 列配置
        cols = {
            "cols": 12
        }
        # 全局配置
        attrs = {}
        # 拼装页面元素
        elements = self.__get_total_elements()
        return cols, attrs, elements

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
            拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
            """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enable',
                                            'label': '启用',
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False
        }

    def get_page(self) -> List[dict]:
        return self.__get_total_elements()

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass

    @staticmethod
    def get_weather_image(path: str, apikey: str) -> Any:
        """
        读取图片
        """
        if apikey != settings.API_TOKEN:
            return None
        if not path:
            return None
        path_obj = Path(path)
        if not path_obj.exists():
            return None
        if not path_obj.is_file():
            return None
        # 判断是否图片文件
        if path_obj.suffix.lower() not in [".jpg", ".png", ".gif", ".bmp", ".jpeg", ".webp"]:
            return None
        return Response(content=path_obj.read_bytes(), media_type="image/jpeg")

    def __update_config(self):
        pass

    def __get_location(self):
        # https://geoapi.qweather.com/v2/city/lookup?key=bdd98ec1d87747f3a2e8b1741a5af796&location=深圳&lang=zh
        pass

    def __take_screenshots(self, location: str):
        """管理多设备截图任务"""
        base_folder_path = settings.CONFIG_PATH / "plugins" / self.__class__.__name__ / "images"
        base_folder_path.mkdir(parents=True, exist_ok=True)  # 确保基础路径存在
        with ThreadPoolExecutor(max_workers=len(SCREENSHOT_DEVICES)) as executor:
            futures = [
                executor.submit(
                    self.screenshot_element,
                    location,
                    key,
                    device,  # 获取设备的详细配置
                    base_folder_path
                ) for key, device in SCREENSHOT_DEVICES.items()
            ]
            for future in futures:
                try:
                    future.result()  # 尝试获取任务结果
                except Exception as e:
                    logger.error(e)

    def __screenshot_element(self, location: str, key: str, device: str, base_folder_path: Path, timeout: int = 30):
        """执行单个截图任务"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        url = f"https://www.qweather.com/weather/{location}.html"
        selector = ".c-city-weather-current"
        image_path = base_folder_path / f"weather_{key}_{timestamp}.png"

        logger.info(f"开始加载 {key} 页面: {url}")
        context = self._browser.new_context(**self._playwright.devices[device])
        page = context.new_page()
        try:
            page.goto(url, wait_until='load', timeout=timeout * 1000)
            page.wait_for_selector(selector, timeout=timeout * 1000)
            logger.info(f"{key} 页面加载成功，标题: {page.title()}")
            element = page.query_selector(selector)
            if element:
                element.screenshot(path=image_path)
                logger.info(f"{key} 截图成功，截图路径: {image_path}")
                self.__manage_images(base_folder_path, key)
            else:
                logger.warning(f"{key} 未找到指定的选择器: {selector}")
        except Exception as e:
            logger.error(f"{key} 截图失败，URL: {url}, 错误：{e}")
        finally:
            context.close()

    @staticmethod
    def __manage_images(folder_path: Path, key: str, max_files: int = 5):
        """管理图片文件，确保每种类型最多保留 max_files 张"""
        files = sorted(folder_path.glob(f"weather_{key}_*.png"), key=lambda x: x.stat().st_mtime)
        if len(files) > max_files:
            for file in files[:-max_files]:
                file.unlink()
                logger.info(f"删除旧图片: {file}")

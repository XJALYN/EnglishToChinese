"""CosyVoice v3-flash 预置音色（摘自百炼官方音色列表）."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TtsVoiceOption:
    voice_id: str
    label: str
    category: str


# cosyvoice-v3-flash 支持的系统音色；同声传译场景优先列出中文普通话
TTS_VOICE_OPTIONS: list[TtsVoiceOption] = [
    # —— 推荐（同声传译）——
    TtsVoiceOption("longxiaochun_v3", "龙小淳 · 知性积极女", "推荐"),
    TtsVoiceOption("longxiaoxia_v3", "龙小夏 · 沉稳权威女", "推荐"),
    TtsVoiceOption("longwan_v3", "龙婉 · 细腻柔声女", "推荐"),
    TtsVoiceOption("longyue_v3", "龙悦 · 温暖磁性女", "推荐"),
    TtsVoiceOption("longmiao_v3", "龙妙 · 抑扬顿挫女", "推荐"),
    TtsVoiceOption("longanyang", "龙安洋 · 阳光大男孩", "推荐"),
    TtsVoiceOption("longcheng_v3", "龙橙 · 智慧青年男", "推荐"),
    TtsVoiceOption("longze_v3", "龙泽 · 温暖元气男", "推荐"),
    TtsVoiceOption("longtian_v3", "龙天 · 磁性理智男", "推荐"),
    TtsVoiceOption("longanzhi_v3", "龙安智 · 睿智轻熟男", "推荐"),
    # —— 女声 ——
    TtsVoiceOption("longanhuan_v3", "龙安欢 · 欢脱元气女", "女声"),
    TtsVoiceOption("longanwen_v3", "龙安温 · 优雅知性女", "女声"),
    TtsVoiceOption("longanli_v3", "龙安莉 · 利落从容女", "女声"),
    TtsVoiceOption("longanling_v3", "龙安灵 · 思维灵动女", "女声"),
    TtsVoiceOption("longanya_v3", "龙安雅 · 高雅气质女", "女声"),
    TtsVoiceOption("longanqin_v3", "龙安亲 · 亲和活泼女", "女声"),
    TtsVoiceOption("longanrou_v3", "龙安柔 · 温柔闺蜜女", "女声"),
    TtsVoiceOption("longyan_v3", "龙颜 · 温暖春风女", "女声"),
    TtsVoiceOption("longxing_v3", "龙星 · 温婉邻家女", "女声"),
    TtsVoiceOption("longfeifei_v3", "龙菲菲 · 甜美娇气女", "女声"),
    TtsVoiceOption("longyumi_v3", "YUMI · 正经青年女", "女声"),
    TtsVoiceOption("longyingling_v3", "龙应聆 · 温和共情女", "女声"),
    TtsVoiceOption("longyingjing_v3", "龙应静 · 低调冷静女", "女声"),
    TtsVoiceOption("longyingtao_v3", "龙应桃 · 温柔淡定女", "女声"),
    TtsVoiceOption("longyuan_v3", "龙媛 · 温暖治愈女", "女声"),
    TtsVoiceOption("longhua_v3", "龙华 · 元气甜美女", "女声"),
    TtsVoiceOption("longantai_v3", "龙安台 · 嗲甜台湾女", "女声"),
    # —— 男声 ——
    TtsVoiceOption("longanlang_v3", "龙安朗 · 清爽利落男", "男声"),
    TtsVoiceOption("longanyun_v3", "龙安昀 · 居家暖男", "男声"),
    TtsVoiceOption("longzhe_v3", "龙哲 · 呆板大暖男", "男声"),
    TtsVoiceOption("longhan_v3", "龙寒 · 温暖痴情男", "男声"),
    TtsVoiceOption("longhao_v3", "龙浩 · 多情忧郁男", "男声"),
    TtsVoiceOption("longfei_v3", "龙飞 · 热血磁性男", "男声"),
    TtsVoiceOption("longxiu_v3", "龙修 · 博才说书男", "男声"),
    TtsVoiceOption("longsanshu_v3", "龙三叔 · 沉稳质感男", "男声"),
    TtsVoiceOption("longnan_v3", "龙楠 · 睿智青年男", "男声"),
    TtsVoiceOption("longyichen_v3", "龙逸尘 · 洒脱活力男", "男声"),
    TtsVoiceOption("longyingxun_v3", "龙应询 · 年轻青涩男", "男声"),
    # —— 有声书 / 解说 ——
    TtsVoiceOption("longwanjun_v3", "龙婉君 · 细腻柔声女", "有声书"),
    TtsVoiceOption("longlaobo_v3", "龙老伯 · 沧桑岁月爷", "有声书"),
    TtsVoiceOption("longlaoyi_v3", "龙老姨 · 烟火从容阿姨", "有声书"),
    TtsVoiceOption("longqiang_v3", "龙嫱 · 浪漫风情女", "有声书"),
    # —— 方言 ——
    TtsVoiceOption("longlaotie_v3", "龙老铁 · 东北直率男", "方言"),
    TtsVoiceOption("longshange_v3", "龙陕哥 · 原味陕北男", "方言"),
    TtsVoiceOption("longjiaxin_v3", "龙嘉欣 · 优雅粤语女", "方言"),
    TtsVoiceOption("longjiayi_v3", "龙嘉怡 · 知性粤语女", "方言"),
    TtsVoiceOption("longanyue_v3", "龙安粤 · 欢脱粤语男", "方言"),
    TtsVoiceOption("longanmin_v3", "龙安闽 · 清纯萝莉女（闽南）", "方言"),
    # —— 童声 ——
    TtsVoiceOption("longhuhu_v3", "龙呼呼 · 天真烂漫女童", "童声"),
    TtsVoiceOption("longniuniu_v3", "龙牛牛 · 阳光男童声", "童声"),
    TtsVoiceOption("longshanshan_v3", "龙闪闪 · 戏剧化童声", "童声"),
    # —— 英文 / 多语言 ——
    TtsVoiceOption("loongabby_v3", "LoongAbby · 美式英文女", "多语言"),
    TtsVoiceOption("loongandy_v3", "LoongAndy · 美式英文男", "多语言"),
    TtsVoiceOption("loongemily_v3", "LoongEmily · 英式英文女", "多语言"),
    TtsVoiceOption("loongeric_v3", "LoongEric · 英式英文男", "多语言"),
    TtsVoiceOption("loongriko_v3", "Riko · 日语女", "多语言"),
    TtsVoiceOption("loongtomoka_v3", "LoongTomoka · 日语女", "多语言"),
    TtsVoiceOption("loongkyong_v3", "LoongKyong · 韩语女", "多语言"),
    TtsVoiceOption("loongjihun_v3", "Jihun · 韩语男", "多语言"),
]

TTS_VOICES: list[str] = [v.voice_id for v in TTS_VOICE_OPTIONS]


def tts_voice_catalog() -> list[dict[str, str]]:
    """供 API / Electron 使用的音色目录."""
    return [
        {"id": v.voice_id, "label": v.label, "category": v.category}
        for v in TTS_VOICE_OPTIONS
    ]

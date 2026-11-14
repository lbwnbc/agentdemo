"""工作流运行参数（第 10 步）：模式 × 档位 → RunSpec。

档位即契约：目标篇数区间、精读篇数与 Collect 轮数预算绑定为一组，
只能整组替换，不允许单独改动其中一项。数值取自 DESIGN.md §2.2 / §4.3。
"""
from __future__ import annotations

from dataclasses import dataclass

MODES = ("survey", "deep")
LEVELS = ("low", "mid", "high")

# (target_min, target_max, read_k)
PRESETS = {
    ("survey", "low"): (10, 15, 0),
    ("survey", "mid"): (15, 100, 0),
    ("survey", "high"): (100, 500, 0),
    ("deep", "low"): (10, 15, 8),
    ("deep", "mid"): (15, 30, 12),
    ("deep", "high"): (30, 50, 20),
}

# Collect 阶段的模型轮数预算，随档位提高（分页与放宽需要更多轮次）。
COLLECT_TURNS = {
    "survey": {"low": 4, "mid": 6, "high": 10},
    "deep": {"low": 10, "mid": 12, "high": 16},
}


@dataclass(frozen=True)
class RunSpec:
    """一次工作流运行的完整参数。"""

    topic: str
    mode: str = "deep"
    level: str = "low"
    target_min: int = 10
    target_max: int = 15
    read_k: int = 8
    max_turns: int = 10
    survey_ids: tuple = ()

    @property
    def label(self):
        return "{}/{}".format(self.mode, self.level)

    def describe(self):
        """给模型与日志看的一行档位说明。"""
        scope = "[{}] 候选论文去重后至少 {} 篇（目标 {} 篇）".format(
            self.label, self.target_min, self.target_max
        )
        if self.read_k:
            return "{}；精读上限 {} 篇".format(scope, self.read_k)
        return "{}；只归集元数据，不精读全文".format(scope)


def preset(mode, level):
    key = (str(mode or "").strip(), str(level or "").strip())
    if key not in PRESETS:
        raise ValueError(
            "未知的模式/档位组合：{}/{}，mode 可选 {}，level 可选 {}".format(
                key[0], key[1], "/".join(MODES), "/".join(LEVELS)
            )
        )
    return PRESETS[key]


def resolve(topic, mode="deep", level="low", survey_ids=None):
    """把主题、模式、档位解析成 RunSpec；survey_ids 为导入的清单（第 13 步）。"""
    topic = " ".join(str(topic or "").split())
    if not topic:
        raise ValueError("研究主题不能为空")
    mode = "deep" if mode is None else str(mode).strip()
    level = "low" if level is None else str(level).strip()
    target_min, target_max, read_k = preset(mode, level)

    ids = tuple(item for item in (survey_ids or ()) if str(item).strip())
    if len(ids) > 3:
        raise ValueError("一次最多导入 3 份清单，当前给了 {} 份".format(len(ids)))
    if ids and mode != "deep":
        raise ValueError("清单导入只适用于 deep 模式")

    return RunSpec(
        topic=topic,
        mode=mode,
        level=level,
        target_min=target_min,
        target_max=target_max,
        read_k=read_k,
        max_turns=COLLECT_TURNS[mode][level],
        survey_ids=ids,
    )

"""Nuke 캐시 갱신 — format, colorspace, datatype 목록을 캐시 파일로 저장."""

from __future__ import annotations

import nuke

from bpe.core.cache import (
    save_colorspaces_cache,
    save_datatypes_cache,
    save_nuke_formats_cache,
)


def refresh_setup_pro_caches() -> None:
    """Nuke 내부에서 실제로 가능한 목록을 긁어서 캐시에 저장한다."""
    # formats 캐시
    formats_dict = {}
    for fmt in nuke.formats():
        try:
            formats_dict[fmt.name()] = {
                "width": int(fmt.width()),
                "height": int(fmt.height()),
            }
        except Exception:
            continue
    save_nuke_formats_cache(formats_dict)

    # colorspace/datatype 캐시 (임시 Write 노드에서 enum 값을 읽음)
    write = nuke.nodes.Write()
    colorspaces = []
    datatypes = []
    try:
        colorspace_candidates = [
            "colorspace",
            "colorSpace",
            "OCIO_colorspace",
            "ocio_colorspace",
            "ocioColorSpace",
        ]
        datatype_candidates = [
            "datatype",
            "dataType",
            "data_type",
            "bitdepth",
            "bitDepth",
            "bit_depth",
        ]

        for knob_name in colorspace_candidates:
            k = write.knob(knob_name)
            if not k:
                continue
            try:
                if hasattr(k, "values"):
                    colorspaces = list(k.values())
                    if colorspaces:
                        break
            except Exception:
                pass

        for knob_name in datatype_candidates:
            k = write.knob(knob_name)
            if not k:
                continue
            try:
                if hasattr(k, "values"):
                    datatypes = list(k.values())
                    if datatypes:
                        break
            except Exception:
                pass

        # 안전장치: datatype 계열 knob 전체를 훑어서 값 수집
        if not datatypes:
            try:
                knobs_obj = write.knobs()
                all_knobs = (
                    list(knobs_obj.values()) if isinstance(knobs_obj, dict) else list(knobs_obj)
                )
                for k in all_knobs:
                    try:
                        kn = k.name()
                    except Exception:
                        kn = str(k)
                    knl = str(kn).lower()
                    if any(
                        s in knl
                        for s in ["datatype", "data_type", "bitdepth", "bit_depth", "bit", "depth"]
                    ):
                        if hasattr(k, "values"):
                            vals = list(k.values())
                            if vals:
                                datatypes = vals
                                break
            except Exception:
                pass
    finally:
        try:
            nuke.delete(write)
        except Exception:
            pass

    # 빈 리스트로 캐시를 덮어쓰면 UI 목록이 사라지므로, 값이 있을 때만 저장
    if colorspaces:
        save_colorspaces_cache(colorspaces)
    else:
        nuke.tprint(
            f"[setup_pro] colorspaces 캐시 갱신 실패/비어 있음({len(colorspaces)}). "
            "기존 캐시를 유지합니다."
        )

    if datatypes:
        save_datatypes_cache(datatypes)
    else:
        nuke.tprint(
            f"[setup_pro] datatypes 캐시 갱신 실패/비어 있음({len(datatypes)}). "
            "기존 캐시를 유지합니다."
        )

    if not colorspaces or not datatypes:
        nuke.tprint(
            "[setup_pro] 캐시 갱신 중 일부 목록을 못 읽었습니다.\n"
            f"- colorspaces: {len(colorspaces)}\n"
            f"- datatypes: {len(datatypes)}\n"
            "해결: Nuke에서 Write 노드에 보이는 컬러스페이스/데이터타입 knob 이름을 알려주세요."
        )
        return

    nuke.tprint(
        "[setup_pro] 캐시 갱신 완료\n"
        f"- formats: {len(formats_dict)}\n"
        f"- colorspaces: {len(colorspaces)}\n"
        f"- datatypes: {len(datatypes)}"
    )

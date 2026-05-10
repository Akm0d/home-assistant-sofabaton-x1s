from pathlib import Path


def test_card_loader_registers_cards_without_waiting_for_domcontentloaded() -> None:
    source = Path("custom_components/sofabaton_x1s/www/card-loader.js").read_text(
        encoding="utf-8",
    )

    assert 'document.addEventListener("DOMContentLoaded", boot)' not in source
    assert 'customElements.whenDefined("sofabaton-control-panel")' in source


def test_card_loader_dispatches_rebuild_after_modules_finish_loading() -> None:
    source = Path("custom_components/sofabaton_x1s/www/card-loader.js").read_text(
        encoding="utf-8",
    )

    assert "queueMicrotask(dispatchRebuild)" in source
    assert 'window.dispatchEvent(new Event("ll-rebuild"' in source
    assert "BOOT_CACHE_ID" in source

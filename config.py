"""
Configuration for the indenture extractor mini-app.
Discovered by the framework's scanner at startup.
"""
APP = {
    "slug": "indenture",
    "name": "Indenture Term Extractor",
    "description": (
        "Extract defined terms from credit agreements, "
        "CLO indentures, and ISDA agreements."
    ),
    "icon": "📑",
    "version": "1.1.0",
    # 1.1.0: runs on SEC EDGAR exhibits through analytics_app.edgar.get_exhibit (contract v1.7.0)
    "requires_framework": ">=1.7,<2",
    # Approved for the live site (contract v1.3). Also needs
    # PLUGINS_EXTERNAL_ALLOWLIST to pin this slug at this exact version.
    "external": True,
}

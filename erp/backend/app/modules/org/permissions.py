"""Permission keys of the org feature.

Acting on approval requests needs no permission: it is governed by the approval rules.
"""

PERMISSIONS: dict[str, str] = {
    "org.company.view": "Şirket bilgilerini görüntüleme",
    "org.company.manage": "Şirket ekleme, düzenleme ve logo yükleme",
    "org.structure.view": "İşyeri, depo ve satınalma gruplarını görüntüleme",
    "org.structure.manage": "İşyeri, depo ve satınalma grubu ekleme, düzenleme ve silme",
    "org.currency.view": "Para birimlerini ve döviz kurlarını görüntüleme",
    "org.currency.manage": "Para birimi ve döviz kuru ekleme, düzenleme, silme ve içe aktarma",
    "org.uom.view": "Ölçü birimlerini görüntüleme",
    "org.uom.manage": "Ölçü birimi ekleme, düzenleme ve silme",
    "org.numbering.view": "Numara aralıklarını görüntüleme",
    "org.numbering.manage": "Numara aralıklarını düzenleme",
    "org.settings.view": "Şirket ayarlarını görüntüleme",
    "org.settings.manage": "Şirket ayarlarını değiştirme",
    "org.approvalrule.view": "Onay kurallarını görüntüleme",
    "org.approvalrule.manage": "Onay kuralı ekleme, düzenleme ve silme",
    "org.audit.view": "Denetim kayıtlarını görüntüleme",
    "org.attachment.view": "Belge eklerini görüntüleme ve indirme",
    "org.attachment.manage": "Belge eki yükleme ve silme",
}

// Örnek Konsey playbook'u — tekrar kullanılabilir desen şablonu.
// Gerçek projeler kendi playbook'larını playbooks/*.js olarak ekler (gitignore'lu;
// yalnız example-*.js yayınlanır). Bu dosya yapıyı gösterir.

export const meta = {
  name: 'example-pipeline',
  description: '3-düğüm karar → paralel tasarım → adversarial doğrulama (salt-okunur tasarım)',
  phases: [
    { title: 'Karar',   detail: '3 paralel düğüm seçenekleri sıralar + sentez ortak karar' },
    { title: 'Tasarım', detail: 'her madde için paralel ajan kesin plan üretir' },
    { title: 'Doğrula', detail: 'her tasarımı adversarial doğrula' },
  ],
}

const READONLY = 'Salt-OKU. Hiçbir dosyayı değiştirme; Read/Grep/Glob kullan. Proje kökü: <KÖK>.'

phase('Karar')
const lenses = [
  { label: 'Risk lensi',   focus: 'Bağımlılık + teknik risk: en az bağımlı, geri-alınabilir önce.' },
  { label: 'Değer lensi',  focus: 'İş değeri: en kısa zamanda doğrulanabilir değer üreten sıralama.' },
  { label: 'Güvenlik lensi', focus: 'Güvenlik/uyum riskini düşüren maddeler; insan-kapısı olanları ayır.' },
]
const proposals = (await parallel(lenses.map(l => () =>
  agent(`Sen Konsey'in bir düğümüsün. Görevleri SIRALA. Lensin: ${l.focus}\n\n${READONLY}`,
    { label: l.label, phase: 'Karar' })
))).filter(Boolean)

const synth = await agent(
  `3 düğümün sıralamasını TEK ortak karara sentezle. Çelişkileri kanıtla çöz (konsensüs değil).\n\n${JSON.stringify(proposals, null, 1)}`,
  { label: 'Ortak karar', phase: 'Karar' }
)

log(`Ortak karar üretildi.`)
return { synth, proposals }

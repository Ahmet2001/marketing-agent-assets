# TikTok Entegrasyonu — Kurulum Adımları

Bu dosya, Kara Tahta'ya eklenen TikTok Content Posting API entegrasyonunu
(services/tiktokPublish.js, POST /api/publish-tiktok) devreye almak için
gereken adımları anlatır.

---

## 1. TikTok Developer Portal Formu İçin Hazır Bilgiler

- **Category**: Education
- **Description** (≤120 karakter):
  `AI turns any topic into a short animated lesson video, published automatically to TikTok.`
- **Terms of Service URL**:
  `https://karatahta-backend-production.up.railway.app/terms`
- **Privacy Policy URL**:
  `https://karatahta-backend-production.up.railway.app/privacy`

Bu iki sayfa zaten backend'de canlı (server.js'e eklendi), doğrudan
kopyalayıp forma yapıştırabilirsin.

---

## 2. TikTok Developer App Oluştur

1. https://developers.tiktok.com/ adresine git, işletme hesabınla giriş yap.
2. "Manage apps" → "Create an app".
3. Formu 1. bölümdeki bilgilerle doldur (Category, Description, ToS/Privacy URL).
4. **Products** kısmına **Content Posting API** ekle.
5. **Scopes** kısmına `video.publish` ve `video.upload` ekle.
6. App oluşturulduktan sonra **Client Key** ve **Client Secret** değerlerini
   kopyala (bunları bana ver, Railway'e ekleyeceğim).

---

## 3. Railway Ortam Değişkenleri

Aşağıdaki değişkenler `karatahta-backend` servisine eklenecek (Railway CLI
ile ben ekleyebilirim, sadece değerleri bana ver):

| Değişken | Nereden alınır |
|---|---|
| `TIKTOK_CLIENT_KEY` | TikTok Developer Portal → App → Basic Information |
| `TIKTOK_CLIENT_SECRET` | TikTok Developer Portal → App → Basic Information |
| `TIKTOK_OAUTH_SETUP_TOKEN` | Sen belirlersin — rastgele, uzun, gizli bir metin (örn. `openssl rand -hex 24` çıktısı). Bu, aşağıdaki bootstrap adımını sadece senin başlatabilmen için bir güvenlik anahtarı. |

`TIKTOK_REFRESH_TOKEN` bir sonraki adımda otomatik üretilecek, elle girmene
gerek yok.

---

## 4. Refresh Token'ı Al (Tek Seferlik Tarayıcı Adımı)

Yukarıdaki 3 değişken Railway'e eklenip servis yeniden deploy edildikten sonra:

1. Şu linki tarayıcında aç (setup_token'ı kendi belirlediğin değerle değiştir):
   ```
   https://karatahta-backend-production.up.railway.app/api/oauth/tiktok/start?setup_token=SENIN_SETUP_TOKEN_DEGERIN
   ```
2. TikTok'un giriş/izin ekranı açılır — **işletme hesabınla** giriş yapıp izin ver.
3. Yönlendirildiğin sayfada bir JSON görünür, içinde `refresh_token` alanı olur.
4. O `refresh_token` değerini kopyala, bana ver — `TIKTOK_REFRESH_TOKEN` olarak
   Railway'e ekleyip servisi yeniden deploy edeceğim.

---

## 5. Önemli Kısıtlama — App Review Onaylanana Kadar

TikTok, henüz **app review**'dan geçmemiş uygulamaların yalnızca
**SELF_ONLY (yalnızca kendine özel/taslak)** olarak video yayınlamasına izin
verir. `services/tiktokPublish.js` bunu zaten varsayılan olarak
`privacyLevel: 'SELF_ONLY'` ile yapıyor — yani entegrasyon çalışır ama
yayınlanan videoyu **yalnızca sen** (TikTok uygulamasında "Yöneticiler"
altında) görebilirsin, herkese açık olmaz.

Herkese açık paylaşım için TikTok'un **App Review** sürecini geçmen gerekiyor
— bu da tam olarak Developer Portal'daki "App review" bölümünde istenen demo
videoyu gerektiriyor. Entegrasyon çalışır hale geldikten sonra (SELF_ONLY ile
test videosu yayınlanabildiğinde) o demo videoyu ben senin için
oluşturabilirim.

---

## 6. Test Etmek İçin

Client key/secret/refresh token Railway'e eklendikten sonra, şu şekilde
manuel test edilebilir:

```
POST https://karatahta-backend-production.up.railway.app/api/publish-tiktok
Body: { "lesson_id": "<bir ders id'si>", "title": "Test" }
```

Bu isteği ben production'da senin adına tetikleyip sonucu doğrulayabilirim.

---

## Sırada Ne Var

- [ ] TikTok Developer app oluştur (madde 2)
- [ ] Client Key / Client Secret'ı bana ver
- [ ] Bir `TIKTOK_OAUTH_SETUP_TOKEN` değeri belirle, bana ver
- [ ] Railway'e ekleyip deploy edeceğim
- [ ] `/api/oauth/tiktok/start` linkini sana vereceğim, tarayıcıda açıp onaylayacaksın
- [ ] `refresh_token`'ı bana verip son adımı tamamlayacağız
- [ ] Test videosu yayınlayıp doğrulayacağız
- [ ] (Opsiyonel, herkese açık paylaşım için) App review demo videosu hazırlayacağız

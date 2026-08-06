import AuthenticationServices
import Capacitor
import Foundation

/// Вход через Apple.
///
/// App Store требует его там, где вход идёт через сторонний сервис
/// (Guideline 4.8) — для дейтинга это частая причина отклонения.
///
/// Наружу отдаём `identityToken` как есть: проверять его на клиенте
/// бессмысленно, подпись проверяет сервер (`api/services/apple_auth.py`).
/// Тело JWT — обычный base64, и «проверка» в приложении ничего не гарантирует.
@objc(AppleSignInPlugin)
public class AppleSignInPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "AppleSignInPlugin"
    public let jsName = "SouldawnAppleSignIn"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "isAvailable", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "signIn", returnType: CAPPluginReturnPromise),
    ]

    /// Держим делегата, пока идёт запрос: `ASAuthorizationController` не
    /// удерживает его сам, и без сильной ссылки он освобождается раньше
    /// ответа — колбэк просто не приходит.
    private var текущий: Делегат?

    @objc public func isAvailable(_ call: CAPPluginCall) {
        if #available(iOS 13.0, *) {
            call.resolve(["available": true])
        } else {
            call.resolve(["available": false])
        }
    }

    @objc public func signIn(_ call: CAPPluginCall) {
        guard #available(iOS 13.0, *) else {
            call.reject("Вход через Apple требует iOS 13")
            return
        }

        DispatchQueue.main.async { [weak self] in
            guard let self else { return }

            let запрос = ASAuthorizationAppleIDProvider().createRequest()
            // Имя и почту Apple отдаёт ТОЛЬКО при первом входе и только если
            // человек их разрешил. Не запросить здесь — значит не получить
            // никогда: повторные входы приходят без них.
            запрос.requestedScopes = [.fullName, .email]

            let делегат = Делегат(call: call) { [weak self] in
                self?.текущий = nil
            }
            self.текущий = делегат

            let контроллер = ASAuthorizationController(authorizationRequests: [запрос])
            контроллер.delegate = делегат
            контроллер.presentationContextProvider = делегат
            контроллер.performRequests()
        }
    }
}

@available(iOS 13.0, *)
private final class Делегат: NSObject, ASAuthorizationControllerDelegate,
                              ASAuthorizationControllerPresentationContextProviding {
    private let call: CAPPluginCall
    private let завершено: () -> Void

    init(call: CAPPluginCall, завершено: @escaping () -> Void) {
        self.call = call
        self.завершено = завершено
    }

    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithAuthorization authorization: ASAuthorization
    ) {
        defer { завершено() }

        guard
            let creds = authorization.credential as? ASAuthorizationAppleIDCredential,
            let данные = creds.identityToken,
            let токен = String(data: данные, encoding: .utf8)
        else {
            call.reject("Apple не вернула токен")
            return
        }

        // Имя собираем из частей: Apple отдаёт их раздельно, и у многих
        // заполнена только одна
        let имя = [creds.fullName?.givenName, creds.fullName?.familyName]
            .compactMap { $0 }
            .joined(separator: " ")

        call.resolve([
            "identityToken": токен,
            "fullName": имя,
            // Почта приходит только при первом входе; сервер на неё не
            // полагается, но для подсказки в анкете годится
            "email": creds.email ?? "",
        ])
    }

    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithError error: Error
    ) {
        defer { завершено() }

        // Отмену отличаем от сбоя: показывать «ошибка входа» тому, кто сам
        // закрыл окно, — значит пугать на ровном месте
        if let e = error as? ASAuthorizationError, e.code == .canceled {
            call.reject("canceled", "canceled")
            return
        }
        call.reject(error.localizedDescription)
    }

    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        // Окно берём у активной сцены: у приложения оно одно, но обращаться
        // к устаревшему `UIApplication.shared.windows` нельзя
        let сцена = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .first { $0.activationState == .foregroundActive }
        return сцена?.keyWindow ?? ASPresentationAnchor()
    }
}

import Capacitor
import Foundation

/// Мост StoreKit 2 в JS. Методы асинхронные, поэтому каждый заворачивается
/// в Task: `call.resolve()` должен произойти после завершения покупки,
/// а не сразу после её начала.
@objc(IAPPlugin)
public class IAPPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "IAPPlugin"
    public let jsName = "SouldawnIAP"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "isAvailable", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "getProducts", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "purchase", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "finishTransaction", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "getCurrentEntitlements", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "startListening", returnType: CAPPluginReturnPromise),
    ]

    private let implementation: Any? = {
        if #available(iOS 16.0, *) { return IAP() }
        return nil
    }()

    @available(iOS 16.0, *)
    private var iap: IAP? { implementation as? IAP }

    @objc public func isAvailable(_ call: CAPPluginCall) {
        if #available(iOS 16.0, *) {
            call.resolve(["available": true])
        } else {
            // StoreKit 2 требует iOS 16 — на старых версиях покупка недоступна
            call.resolve(["available": false])
        }
    }

    @objc public func getProducts(_ call: CAPPluginCall) {
        guard #available(iOS 16.0, *), let iap else {
            call.reject("StoreKit 2 требует iOS 16")
            return
        }
        let ids = call.getArray("productIds", String.self) ?? []
        guard !ids.isEmpty else {
            call.reject("productIds обязателен")
            return
        }
        Task {
            do {
                call.resolve(["products": try await iap.products(for: ids)])
            } catch {
                call.reject(error.localizedDescription)
            }
        }
    }

    @objc public func purchase(_ call: CAPPluginCall) {
        guard #available(iOS 16.0, *), let iap else {
            call.reject("StoreKit 2 требует iOS 16")
            return
        }
        guard let productId = call.getString("productId") else {
            call.reject("productId обязателен")
            return
        }
        // UUID, а не произвольная строка: Apple игнорирует иной формат,
        // и тогда сервер не сможет связать покупку с пользователем
        let token = call.getString("appAccountToken").flatMap(UUID.init(uuidString:))

        Task {
            do {
                call.resolve(try await iap.purchase(productId: productId, appAccountToken: token))
            } catch {
                // Отмена — не ошибка приложения, различаем её по коду
                if case IAP.IAPError.cancelled = error {
                    call.reject("cancelled", "cancelled")
                } else if case IAP.IAPError.pending = error {
                    call.reject("pending", "pending")
                } else {
                    call.reject(error.localizedDescription)
                }
            }
        }
    }

    @objc public func finishTransaction(_ call: CAPPluginCall) {
        guard #available(iOS 16.0, *), let iap else {
            call.reject("StoreKit 2 требует iOS 16")
            return
        }
        guard let transactionId = call.getString("transactionId") else {
            call.reject("transactionId обязателен")
            return
        }
        Task {
            await iap.finish(transactionId: transactionId)
            call.resolve()
        }
    }

    @objc public func getCurrentEntitlements(_ call: CAPPluginCall) {
        guard #available(iOS 16.0, *), let iap else {
            call.reject("StoreKit 2 требует iOS 16")
            return
        }
        let force = call.getBool("force") ?? false
        Task {
            do {
                call.resolve(["entitlements": try await iap.currentEntitlements(force: force)])
            } catch {
                call.reject(error.localizedDescription)
            }
        }
    }

    /// Подписка на транзакции, приходящие вне покупки: продления и покупки
    /// с другого устройства. События уходят в JS как `transactionUpdate`.
    @objc public func startListening(_ call: CAPPluginCall) {
        guard #available(iOS 16.0, *), let iap else {
            call.reject("StoreKit 2 требует iOS 16")
            return
        }
        iap.startObservingUpdates { [weak self] payload in
            self?.notifyListeners("transactionUpdate", data: payload)
        }
        call.resolve()
    }
}

import Foundation
import StoreKit

/// Покупка Premium через StoreKit 2.
///
/// Плагин намеренно не решает, есть ли у пользователя подписка: это решает
/// сервер, проверив подпись Apple. Здесь только покупка и передача наверх
/// подписанной транзакции (`jwsRepresentation`).
///
/// Транзакция подтверждается (`finish()`) лишь после того, как сервер её
/// принял. Если подтвердить раньше и запрос не дойдёт, деньги списаны, а
/// доступа нет: повторно получить ту же транзакцию будет уже нельзя.
@available(iOS 16.0, *)
public class IAP: NSObject {

    public enum IAPError: LocalizedError {
        case productNotFound(String)
        case unverified
        case cancelled
        case pending

        public var errorDescription: String? {
            switch self {
            case .productNotFound(let id): return "Продукт \(id) недоступен"
            case .unverified: return "Apple не подтвердила покупку"
            case .cancelled: return "Покупка отменена"
            case .pending: return "Покупка ожидает подтверждения"
            }
        }
    }

    /// Незавершённые транзакции: ключ — идентификатор, значение — сама
    /// транзакция. Финализируем по команде из JS, когда сервер ответил.
    private var pending: [String: StoreKit.Transaction] = [:]
    private var updatesTask: Task<Void, Never>?

    /// Транзакции, пришедшие вне процесса покупки: продления, покупки с
    /// другого устройства, отложенные подтверждения (Ask to Buy). Без этого
    /// слушателя продление подписки сервер не увидит вовсе.
    public func startObservingUpdates(onTransaction: @escaping ([String: Any]) -> Void) {
        guard updatesTask == nil else { return }
        updatesTask = Task.detached { [weak self] in
            for await update in StoreKit.Transaction.updates {
                guard let self, case .verified(let transaction) = update else { continue }
                let key = String(transaction.id)
                await self.remember(key: key, transaction: transaction)
                onTransaction([
                    "transactionId": key,
                    "productId": transaction.productID,
                    "jws": update.jwsRepresentation,
                ])
            }
        }
    }

    public func stopObservingUpdates() {
        updatesTask?.cancel()
        updatesTask = nil
    }

    @MainActor
    private func remember(key: String, transaction: StoreKit.Transaction) {
        pending[key] = transaction
    }

    public func products(for ids: [String]) async throws -> [[String: Any]] {
        let products = try await Product.products(for: ids)
        return products.map { product in
            [
                "id": product.id,
                "title": product.displayName,
                "description": product.description,
                "price": product.displayPrice,
                "priceValue": NSDecimalNumber(decimal: product.price).doubleValue,
                "currency": product.priceFormatStyle.currencyCode,
            ]
        }
    }

    /// Покупка. `appAccountToken` привязывает транзакцию к пользователю нашего
    /// сервера — без него валидный чужой чек можно предъявить с любого аккаунта.
    public func purchase(productId: String, appAccountToken: UUID?) async throws -> [String: Any] {
        let products = try await Product.products(for: [productId])
        guard let product = products.first else {
            throw IAPError.productNotFound(productId)
        }

        var options: Set<Product.PurchaseOption> = []
        if let token = appAccountToken {
            options.insert(.appAccountToken(token))
        }

        let result = try await product.purchase(options: options)

        switch result {
        case .success(let verification):
            // .unverified — провал проверки подписи, а не «почти успех»
            guard case .verified(let transaction) = verification else {
                throw IAPError.unverified
            }
            let key = String(transaction.id)
            await remember(key: key, transaction: transaction)
            return [
                "transactionId": key,
                "productId": transaction.productID,
                "jws": verification.jwsRepresentation,
            ]

        case .userCancelled:
            throw IAPError.cancelled

        case .pending:
            // Ask to Buy: решение придёт позже в Transaction.updates
            throw IAPError.pending

        @unknown default:
            throw IAPError.unverified
        }
    }

    /// Подтвердить транзакцию — только после того, как сервер её зачёл.
    public func finish(transactionId: String) async {
        guard let transaction = await popPending(transactionId) else { return }
        await transaction.finish()
    }

    @MainActor
    private func popPending(_ key: String) -> StoreKit.Transaction? {
        pending.removeValue(forKey: key)
    }

    /// Действующие покупки — для кнопки «Восстановить покупки».
    /// `force` вызывает AppStore.sync(): дороже и может спросить пароль,
    /// поэтому только по явному действию пользователя.
    public func currentEntitlements(force: Bool) async throws -> [[String: Any]] {
        if force {
            try await AppStore.sync()
        }

        var entitlements: [[String: Any]] = []
        for await result in StoreKit.Transaction.currentEntitlements {
            guard case .verified(let transaction) = result else { continue }
            // Возврат или чарджбэк — покупка больше не действует
            guard transaction.revocationDate == nil else { continue }
            await remember(key: String(transaction.id), transaction: transaction)
            entitlements.append([
                "transactionId": String(transaction.id),
                "productId": transaction.productID,
                "jws": result.jwsRepresentation,
            ])
        }
        return entitlements
    }
}

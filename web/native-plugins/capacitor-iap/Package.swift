// swift-tools-version: 5.9
import PackageDescription

// Имя продукта выводится Capacitor CLI из имени npm-пакета
// (@souldawn/capacitor-iap → SouldawnCapacitorIap) и подставляется в
// автогенерируемый ios/App/CapApp-SPM/Package.swift. Переименуешь —
// сборка перестанет находить продукт.
let package = Package(
    name: "SouldawnCapacitorIap",
    platforms: [.iOS(.v16)],
    products: [
        .library(
            name: "SouldawnCapacitorIap",
            targets: ["IAPPlugin"])
    ],
    dependencies: [
        .package(url: "https://github.com/ionic-team/capacitor-swift-pm.git", from: "8.0.0")
    ],
    targets: [
        .target(
            name: "IAPPlugin",
            dependencies: [
                .product(name: "Capacitor", package: "capacitor-swift-pm"),
                .product(name: "Cordova", package: "capacitor-swift-pm")
            ],
            path: "ios/Sources/IAPPlugin")
    ]
)

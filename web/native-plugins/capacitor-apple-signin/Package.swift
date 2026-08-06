// swift-tools-version: 5.9
import PackageDescription

// Имя продукта Capacitor CLI выводит из имени npm-пакета
// (@souldawn/capacitor-apple-signin → SouldawnCapacitorAppleSignin) и
// подставляет в автогенерируемый ios/App/CapApp-SPM/Package.swift.
// Переименуешь — сборка перестанет находить продукт.
let package = Package(
    name: "SouldawnCapacitorAppleSignin",
    platforms: [.iOS(.v16)],
    products: [
        .library(
            name: "SouldawnCapacitorAppleSignin",
            targets: ["AppleSignInPlugin"])
    ],
    dependencies: [
        .package(url: "https://github.com/ionic-team/capacitor-swift-pm.git", from: "8.0.0")
    ],
    targets: [
        .target(
            name: "AppleSignInPlugin",
            dependencies: [
                .product(name: "Capacitor", package: "capacitor-swift-pm"),
                .product(name: "Cordova", package: "capacitor-swift-pm")
            ],
            path: "ios/Sources/AppleSignInPlugin")
    ]
)

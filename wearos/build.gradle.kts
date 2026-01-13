plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.devtools.ksp")
    id("org.jetbrains.kotlin.plugin.compose")
}

java {
    toolchain { languageVersion.set(JavaLanguageVersion.of(21)) }
}

kotlin {
    jvmToolchain(21)
}

val appVersionCode = rootProject.extra["appVersionCode"] as Int
val appVersionName = rootProject.extra["appVersionName"] as String
val releaseStoreFile = rootProject.extra["releaseStoreFile"] as String
val releaseStorePassword = rootProject.extra["releaseStorePassword"] as String
val releaseKeyAlias = rootProject.extra["releaseKeyAlias"] as String
val releaseKeyPassword = rootProject.extra["releaseKeyPassword"] as String
val hasReleaseSigning = rootProject.extra["hasReleaseSigning"] as Boolean

val isReleaseBuild = gradle.startParameter.taskNames.any { taskName ->
    taskName.contains("Release", ignoreCase = true)
}
if (isReleaseBuild && !hasReleaseSigning) {
    throw GradleException(
        "Missing release signing configuration. Provide keystore.properties or MWA_* env vars."
    )
}

android {
    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = file(releaseStoreFile)
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }
    namespace = "com.gabstra.myworkoutassistant"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.gabstra.myworkoutassistant"
        minSdk = 34
        targetSdk = 35
        versionCode = appVersionCode
        versionName = appVersionName
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables {
            useSupportLibrary = true
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
        getByName("debug") {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
    }
    compileOptions {
        isCoreLibraryDesugaringEnabled = true
    }
    buildFeatures {
        compose = true
    }
    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    implementation(project(":shared"))
    implementation("androidx.wear.compose:compose-material-core:1.6.0-alpha07")
    implementation("androidx.navigation:navigation-compose:2.9.6")
    implementation("androidx.compose.ui:ui-graphics:1.10.0")

    // Compose BOM (don't specify versions for androidx.compose.* artifacts)
    val composeBom = platform("androidx.compose:compose-bom:2025.12.01")
    implementation(composeBom)
    testImplementation(composeBom)
    androidTestImplementation(composeBom)

    implementation("androidx.compose.material3:material3")

    // Compose UI
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui-text-google-fonts")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")

    // Wear Compose
    implementation("androidx.wear.compose:compose-material3:1.6.0-alpha07")
    implementation("androidx.wear.compose:compose-navigation:1.6.0-alpha07")
    implementation("androidx.wear.compose:compose-ui-tooling:1.6.0-alpha07")
    implementation("androidx.wear.compose:compose-foundation:1.6.0-alpha07")

    // AndroidX / Google
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.activity:activity-compose:1.12.2")
    implementation("androidx.concurrent:concurrent-futures-ktx:1.3.0")
    implementation("com.google.accompanist:accompanist-permissions:0.37.3")
    implementation("androidx.wear:wear-tooling-preview:1.0.0")
    implementation("androidx.wear:wear-ongoing:1.1.0")
    implementation("com.google.android.gms:play-services-wearable:19.0.0")

    //Horologist
    implementation("com.google.android.horologist:horologist-datalayer:0.8.2-alpha")
    implementation("com.google.android.horologist:horologist-datalayer-watch:0.8.2-alpha")
    implementation("com.google.android.horologist:horologist-composables:0.8.2-alpha")
    implementation("com.google.android.horologist:horologist-compose-layout:0.8.2-alpha")

    // Data / utils
    ksp("androidx.room:room-compiler:2.8.4")
    implementation("androidx.room:room-ktx:2.8.4")
    implementation("com.google.guava:guava:33.5.0-android")
    implementation("com.google.code.gson:gson:2.13.2")

    // Polar SDK + Rx
    implementation("com.github.polarofficial:polar-ble-sdk:6.8.0")
    implementation("io.reactivex.rxjava3:rxjava:3.1.12")
    implementation("io.reactivex.rxjava3:rxandroid:3.0.2")

    // Desugaring
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.5")

    // Misc
    implementation("com.github.kevinnzou:compose-progressindicator:1.0.0")
    implementation("dev.shreyaspatil:capturable:3.0.1")
    // Test
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.mockito:mockito-core:5.21.0")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
    testImplementation("io.mockk:mockk:1.14.7")
    testImplementation("androidx.arch.core:core-testing:2.2.0")
    testImplementation("org.robolectric:robolectric:4.16")
    testImplementation("com.google.truth:truth:1.4.5")
    // Instrumented / E2E Android tests
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test:rules:1.7.0")
    androidTestImplementation("androidx.test:core:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test.uiautomator:uiautomator:2.4.0-alpha07")
}

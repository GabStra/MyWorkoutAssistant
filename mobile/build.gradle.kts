plugins {
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.devtools.ksp")
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
    implementation("androidx.documentfile:documentfile:1.1.0")

    // Compose BOM (Dec 2025)
    val composeBom = platform("androidx.compose:compose-bom:2025.12.01")
    implementation(composeBom)
    testImplementation(composeBom)
    androidTestImplementation(composeBom)

    // Jetpack Compose (BOM-managed; no versions)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")                    // Material 3
    implementation("androidx.compose.material3:material3-window-size-class") // Material 3 adaptive
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")

    // Navigation
    implementation("androidx.navigation:navigation-compose:2.9.7")

    // AndroidX core
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.activity:activity-compose:1.12.3")
    implementation("androidx.work:work-runtime-ktx:2.10.5")

    // Lifecycle
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.10.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.10.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.10.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.10.0")

    // Google / Wear
    implementation("com.google.android.gms:play-services-wearable:19.0.0")
    implementation("com.google.android.horologist:horologist-datalayer:0.7.15")
    implementation("com.google.android.horologist:horologist-datalayer-phone:0.7.15")

    // Accompanist
    implementation("com.google.accompanist:accompanist-permissions:0.37.3")
    implementation("com.google.accompanist:accompanist-systemuicontroller:0.36.0")

    // Room
    ksp("androidx.room:room-compiler:2.8.4")
    implementation("androidx.room:room-runtime:2.8.4")

    // Misc
    implementation("com.google.code.gson:gson:2.13.2")
    implementation("com.patrykandpatrick.vico:compose:2.4.3")
    implementation("com.kizitonwose.calendar:compose:2.10.0")
    implementation("androidx.health.connect:connect-client:1.1.0")
    implementation("com.github.kevinnzou:compose-progressindicator:1.0.0")
    implementation("com.github.nanihadesuka:LazyColumnScrollbar:2.1.0")

    // Tests
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.7.0")
    androidTestImplementation("androidx.test.uiautomator:uiautomator:2.4.0-alpha07")

    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.5")
}





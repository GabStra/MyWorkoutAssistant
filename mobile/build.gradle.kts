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


android {
    signingConfigs {
        getByName("debug") {
            storeFile =
                file("C:\\Users\\gabri\\OneDrive\\MyWorkoutAssistant\\workout_assistant_keystore.jks")
            storePassword = "VDk8D21M4qoPiGP7tRDOAbQF"
            keyAlias = "release_key"
            keyPassword = "GRn24V3dWsToEKVzgoQG2uyB"
        }
        create("release") {
            storeFile =
                file("C:\\Users\\gabri\\OneDrive\\MyWorkoutAssistant\\workout_assistant_keystore.jks")
            storePassword = "VDk8D21M4qoPiGP7tRDOAbQF"
            keyAlias = "release_key"
            keyPassword = "GRn24V3dWsToEKVzgoQG2uyB"
        }
    }
    namespace = "com.gabstra.myworkoutassistant"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.gabstra.myworkoutassistant"
        minSdk = 34
        targetSdk = 35
        versionCode = 1
        versionName = "1"
        vectorDrawables {
            useSupportLibrary = true
        }
        signingConfig = signingConfigs.getByName("release")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            signingConfig = signingConfigs.getByName("release")
        }
        getByName("debug") {
            signingConfig = signingConfigs.getByName("release")
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

    // Compose BOM (Oct 2025)
    val composeBom = platform("androidx.compose:compose-bom:2025.10.00")
    implementation(composeBom)
    testImplementation(composeBom)
    androidTestImplementation(composeBom)

    // Jetpack Compose (BOM-managed; no versions)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")                    // Material 3
    implementation("androidx.compose.material3:material3-window-size-class") // Material 3 adaptive
    implementation("androidx.compose.material:material-icons-extended")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")

    // Navigation
    implementation("androidx.navigation:navigation-compose:2.9.5")

    // AndroidX core
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.activity:activity-compose:1.11.0")

    // Lifecycle
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.9.4")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.4")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.9.4")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.4")

    // Google / Wear
    implementation("com.google.android.gms:play-services-wearable:19.0.0")
    implementation("com.google.android.horologist:horologist-datalayer:0.7.15")
    implementation("com.google.android.horologist:horologist-datalayer-phone:0.7.15")

    // Accompanist
    implementation("com.google.accompanist:accompanist-permissions:0.37.3")
    implementation("com.google.accompanist:accompanist-systemuicontroller:0.36.0")

    // Room
    ksp("androidx.room:room-compiler:2.8.2")
    implementation("androidx.room:room-runtime:2.8.2")

    // Misc
    implementation("com.google.code.gson:gson:2.13.2")
    implementation("com.patrykandpatrick.vico:compose:2.2.1")
    implementation("com.kizitonwose.calendar:compose:2.9.0")
    implementation("androidx.health.connect:connect-client:1.1.0")
    implementation("com.github.kevinnzou:compose-progressindicator:1.0.0")
    implementation("com.github.nanihadesuka:LazyColumnScrollbar:2.1.0")

    // Tests
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.7.0")

    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.5")
}





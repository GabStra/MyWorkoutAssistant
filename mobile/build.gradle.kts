plugins {
    id("org.jetbrains.kotlin.plugin.compose") version "2.0.0"
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.devtools.ksp")
}

composeCompiler {
    enableStrongSkippingMode = true
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
    compileSdk = 35

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
        sourceCompatibility = JavaVersion.VERSION_21
        targetCompatibility = JavaVersion.VERSION_21
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
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("com.google.android.gms:play-services-wearable:19.0.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.activity:activity-compose:1.10.0")
    implementation(platform("androidx.compose:compose-bom:2025.01.00"))
    implementation("com.github.nanihadesuka:LazyColumnScrollbar:2.1.0")

    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.navigation:navigation-compose:2.8.5")

    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("com.google.accompanist:accompanist-systemuicontroller:0.34.0")
    implementation("com.google.accompanist:accompanist-permissions:0.35.0-alpha")
    implementation("com.google.code.gson:gson:2.11.0")
    implementation("androidx.compose.material:material-icons-extended:1.7.6")
    implementation("com.google.accompanist:accompanist-permissions:0.35.0-alpha")
    implementation("com.google.android.horologist:horologist-datalayer:0.6.17")
    implementation("com.google.android.horologist:horologist-datalayer-phone:0.5.21")
    ksp("androidx.room:room-compiler:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
    androidTestImplementation(platform("androidx.compose:compose-bom:2025.01.00"))
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")

    implementation("com.patrykandpatrick.vico:compose:2.1.3")
    implementation("com.kizitonwose.calendar:compose:2.5.0")
    implementation("androidx.health.connect:connect-client:1.1.0-beta01")
    implementation("com.github.kevinnzou:compose-progressindicator:1.0.0")
}





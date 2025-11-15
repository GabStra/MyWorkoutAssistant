plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
    id("com.google.devtools.ksp")
    id("org.jetbrains.kotlin.plugin.compose")
}

ksp {
    arg("room.generateKotlin", "true")
}


java {
    toolchain { languageVersion.set(JavaLanguageVersion.of(21)) }
}

kotlin {
    jvmToolchain(21)
}

android {
    namespace = "com.gabstra.myworkoutassistant.shared"
    compileSdk = 36

    defaultConfig {
        minSdk = 30
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
}

val coroutinesVersion = "1.10.2"

dependencies {
    implementation("androidx.compose.ui:ui-graphics:1.9.3")
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.appcompat:appcompat:1.7.1")
    implementation("com.google.accompanist:accompanist-permissions:0.37.3")
    implementation("com.google.code.gson:gson:2.13.2")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.4")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.9.4")
    implementation("androidx.test.ext:junit-ktx:1.3.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:$coroutinesVersion")

    ksp("androidx.room:room-compiler:2.8.2")
    implementation("androidx.room:room-ktx:2.8.2")

    // Test dependencies
    testImplementation("junit:junit:4.13.2")
    testImplementation("androidx.room:room-testing:2.8.3")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:$coroutinesVersion")
    androidTestImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:$coroutinesVersion")
    testImplementation("androidx.test:core:1.7.0")
    testImplementation("androidx.arch.core:core-testing:2.2.0")
    testImplementation("org.robolectric:robolectric:4.16")
}
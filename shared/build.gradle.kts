plugins {
    id("com.android.library")
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

    sourceSets {
        named("main") {
            kotlin.directories.add("src/main/java")
        }
        named("debug") {
            kotlin.directories.add("src/debug/java")
        }
        named("release") {
            kotlin.directories.add("src/release/java")
        }
        named("androidTest") {
            kotlin.directories.add("src/androidTest/java")
        }
        named("test") {
            kotlin.directories.add("src/test/java")
        }
    }
}



dependencies {
    implementation("androidx.compose.ui:ui-graphics:1.10.6")
    implementation("androidx.core:core-ktx:1.18.0")
    implementation("androidx.appcompat:appcompat:1.7.1")
    implementation("com.google.accompanist:accompanist-permissions:0.37.3")
    implementation("com.google.code.gson:gson:2.13.2")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.10.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.10.0")
    implementation("androidx.test.ext:junit-ktx:1.3.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.10.2")

    ksp("androidx.room:room-compiler:2.8.4")
    implementation("androidx.room:room-ktx:2.8.4")

    // Test dependencies
    testImplementation("junit:junit:4.13.2")
    testImplementation("androidx.room:room-testing:2.8.4")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
    androidTestImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
    testImplementation("androidx.test:core:1.7.0")
    testImplementation("androidx.arch.core:core-testing:2.2.0")
    testImplementation("org.robolectric:robolectric:4.16.1")
}

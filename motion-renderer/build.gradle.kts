plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.plugin.compose")
}

java {
    toolchain { languageVersion.set(JavaLanguageVersion.of(21)) }
}

kotlin {
    jvmToolchain(21)
}

android {
    namespace = "com.gabstra.myworkoutassistant.motionrenderer"
    compileSdk = 37

    defaultConfig {
        minSdk = 34
    }

    buildFeatures {
        compose = true
        buildConfig = false
    }

    sourceSets {
        named("main") {
            kotlin.directories.add("src/main/java")
        }
    }
}

dependencies {
    implementation(project(":shared"))

    val composeBom = platform("androidx.compose:compose-bom:2025.12.01")
    implementation(composeBom)

    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("com.google.android.filament:filament-android:1.74.0")
    implementation("com.google.code.gson:gson:2.14.0")
}

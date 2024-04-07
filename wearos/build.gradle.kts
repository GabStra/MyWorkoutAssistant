import java.util.Properties

val versionPropsFile = file("version.properties.wear")
val versionProps = Properties()

if (versionPropsFile.canRead()) {
    versionProps.load(versionPropsFile.inputStream())
}

// Keep the oldVersionCode unchanged
val oldVersionCode = versionProps["VERSION_CODE"].toString().toInt()

val oldVersionName = versionProps["VERSION_NAME"].toString()
val versionComponents = oldVersionName.split(".")
val majorVersion = versionComponents[0].toInt()
val minorVersion = versionComponents[1].toInt()
// Increment the patch version, or set to 1 if it's not explicitly set
val patchVersion = if (versionComponents.size > 2) versionComponents[2].toInt() + 1 else 1

// Construct the new version name with the incremented patch version
val newVersionName = "$majorVersion.$minorVersion.$patchVersion"

// Update the properties file with the new version name
// Note: We are not updating the VERSION_CODE here, only the VERSION_NAME
versionProps["VERSION_NAME"] = newVersionName
versionProps.store(versionPropsFile.writer(), null)

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("kotlin-kapt")
}

android {
    namespace = "com.gabstra.myworkoutassistant"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.gabstra.myworkoutassistant"
        minSdk = 31
        targetSdk = 34
        versionCode = oldVersionCode
        versionName = newVersionName
        vectorDrawables {
            useSupportLibrary = true
        }

    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17

        isCoreLibraryDesugaringEnabled = true
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
    }
    composeOptions {
        kotlinCompilerExtensionVersion = "1.4.3"
    }
    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    implementation(project(":shared"))
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("com.google.android.gms:play-services-wearable:18.1.0")
    implementation("androidx.percentlayout:percentlayout:1.0.0")
    implementation("androidx.legacy:legacy-support-v4:1.0.0")
    implementation("androidx.recyclerview:recyclerview:1.3.2")
    implementation(platform("androidx.compose:compose-bom:2023.03.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.wear.compose:compose-material:1.3.0")
    implementation("androidx.wear.compose:compose-foundation:1.3.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.7.0")
    implementation("androidx.activity:activity-compose:1.8.2")
    implementation("androidx.navigation:navigation-compose:2.7.6")
    implementation("androidx.health:health-services-client:1.1.0-alpha02")
    implementation("androidx.concurrent:concurrent-futures-ktx:1.1.0")
    implementation("com.google.accompanist:accompanist-permissions:0.33.2-alpha")
    implementation("com.google.android.horologist:horologist-composables:0.5.19")
    implementation("androidx.wear:wear-tooling-preview:1.0.0")
    implementation("com.google.android.horologist:horologist-datalayer:0.5.19")
    implementation("com.google.android.horologist:horologist-datalayer-watch:0.5.19")
    kapt("androidx.room:room-compiler:+")
    implementation("androidx.room:room-ktx:+")
    implementation("androidx.health:health-services-client:1.1.0-alpha02")
    implementation("androidx.concurrent:concurrent-futures-ktx:1.1.0")
    implementation("com.google.guava:guava:30.0-android")
    implementation("androidx.compose.material:material-icons-extended:1.6.0")
    implementation("com.google.code.gson:gson:2.10")
    implementation("com.google.android.horologist:horologist-compose-layout:0.5.19")
    implementation("com.github.polarofficial:polar-ble-sdk:5.5.0")
    implementation("io.reactivex.rxjava3:rxjava:3.1.6")
    implementation("io.reactivex.rxjava3:rxandroid:3.0.2")
    implementation("androidx.compose.foundation:foundation:1.6.0")
    androidTestImplementation(platform("androidx.compose:compose-bom:2023.03.00"))
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.0.4")
}
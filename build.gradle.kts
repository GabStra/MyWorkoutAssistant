import java.util.Properties

// Top-level build file where you can add configuration options common to all sub-projects/modules.
plugins {
    id("com.android.application") version "8.13.2" apply false
    id("com.android.library") version "8.13.2" apply false
    id("org.jetbrains.kotlin.android") version "2.2.20" apply false
    id("com.google.devtools.ksp") version "2.2.20-2.0.3" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.2.20" apply false
}

val versionPropsFile = rootProject.file("version.properties")
check(versionPropsFile.isFile) {
    "Missing version.properties at ${versionPropsFile.absolutePath}"
}
val versionProps = Properties().apply { load(versionPropsFile.inputStream()) }
extra["appVersionCode"] = versionProps.getProperty("VERSION_CODE").toInt()
extra["appVersionName"] = versionProps.getProperty("VERSION_NAME")

val keystorePropsFile = rootProject.file("keystore.properties")
val keystoreProps = Properties().apply {
    if (keystorePropsFile.isFile) {
        load(keystorePropsFile.inputStream())
    }
}
fun readKeystoreValue(key: String, envKey: String): String {
    return keystoreProps.getProperty(key) ?: System.getenv(envKey).orEmpty()
}
val releaseStoreFile = readKeystoreValue("storeFile", "MWA_STORE_FILE")
val releaseStorePassword = readKeystoreValue("storePassword", "MWA_STORE_PASSWORD")
val releaseKeyAlias = readKeystoreValue("keyAlias", "MWA_KEY_ALIAS")
val releaseKeyPassword = readKeystoreValue("keyPassword", "MWA_KEY_PASSWORD")
extra["releaseStoreFile"] = releaseStoreFile
extra["releaseStorePassword"] = releaseStorePassword
extra["releaseKeyAlias"] = releaseKeyAlias
extra["releaseKeyPassword"] = releaseKeyPassword
extra["hasReleaseSigning"] =
    listOf(releaseStoreFile, releaseStorePassword, releaseKeyAlias, releaseKeyPassword)
        .all { it.isNotBlank() }


package com.gabstra.myworkoutassistant

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths
import javax.xml.parsers.DocumentBuilderFactory
import org.w3c.dom.Element

/**
 * Guards the localization contract between the base (English) and translated
 * string resource files: every locale must define every translatable resource
 * name, with the same element tags, the same plural quantities, and the same
 * set of format placeholders per entry. Resources marked translatable="false"
 * in the base locale are intentionally not required in translations. A wrong
 * placeholder is a runtime crash, not a build failure, so it has to be caught
 * here.
 */
class StringResourcesParityTest {

    private val formatSpec = Regex("""%(?:(\d+)\$)?[0-9.]*[sdfb]""")

    private enum class ResourceKind(val xmlTag: String) {
        STRING("string"),
        PLURALS("plurals"),
    }

    private data class ResourceKey(val kind: ResourceKind, val name: String) {
        override fun toString(): String = "${kind.xmlTag}:$name"
    }

    private data class ResourceEntry(
        val kind: ResourceKind,
        val name: String,
        val translatable: Boolean,
        val text: String,
        val pluralItems: Map<String, String>,
        val source: Path,
    )

    private fun placeholders(text: String): Set<String> {
        val unescaped = text.replace("%%", "")
        val specs = formatSpec.findAll(unescaped).map { it.value.replace(Regex("""[0-9.]+\$"""), "") }.toSet()
        assertTrue(
            "Non-positional or unknown format specifiers in: \"$unescaped\" -> $specs",
            formatSpec.findAll(unescaped).all { it.groupValues[1].isNotEmpty() }
        )
        return specs
    }

    private fun repoRoot(): Path {
        var dir: Path? = Paths.get(System.getProperty("user.dir")).toAbsolutePath()
        repeat(8) {
            val candidate = dir ?: return@repeat
            if (Files.isDirectory(candidate.resolve("mobile/src/main/res/values"))) return candidate
            dir = candidate.parent
        }
        throw IllegalStateException("Repo root with mobile string resources not found from user.dir")
    }

    private fun xmlFiles(directory: Path): List<Path> {
        assertTrue("Missing resource directory $directory", Files.isDirectory(directory))
        return Files.newDirectoryStream(directory, "*.xml").use { entries ->
            entries.filter { Files.isRegularFile(it) }.sortedBy { it.fileName.toString() }
        }
    }

    private fun pluralItems(element: Element, source: Path, label: String): Map<String, String> {
        val quantities = mutableMapOf<String, String>()
        for (i in 0 until element.childNodes.length) {
            val item = element.childNodes.item(i) as? Element ?: continue
            if (item.tagName != "item") continue
            val quantity = item.getAttribute("quantity")
            assertTrue(
                "$label:${source.fileName}: plural '${element.getAttribute("name")}' item is missing a quantity",
                quantity.isNotBlank()
            )
            val previous = quantities.put(quantity, item.textContent)
            assertTrue(
                "$label:${source.fileName}: plural '${element.getAttribute("name")}' repeats quantity '$quantity'",
                previous == null
            )
        }
        return quantities
    }

    private fun loadResources(directory: Path, label: String): Map<ResourceKey, ResourceEntry> {
        val out = mutableMapOf<ResourceKey, ResourceEntry>()
        for (file in xmlFiles(directory)) {
            val doc = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(file.toFile())
            val root = doc.documentElement
            for (i in 0 until root.childNodes.length) {
                val element = root.childNodes.item(i) as? Element ?: continue
                val kind = ResourceKind.entries.firstOrNull { it.xmlTag == element.tagName } ?: continue
                val name = element.getAttribute("name")
                assertTrue(
                    "$label:${file.fileName}: <${element.tagName}> is missing a name",
                    name.isNotBlank()
                )
                val entry = ResourceEntry(
                    kind = kind,
                    name = name,
                    translatable = !element.getAttribute("translatable").equals("false", ignoreCase = true),
                    text = element.textContent,
                    pluralItems = if (kind == ResourceKind.PLURALS) pluralItems(element, file, label) else emptyMap(),
                    source = file,
                )
                val key = ResourceKey(kind, name)
                val previous = out.putIfAbsent(key, entry)
                assertTrue(
                    "$label:${file.fileName}: duplicate $key, already defined in ${previous?.source?.fileName}",
                    previous == null
                )
            }
        }
        return out
    }

    private fun assertParity(module: String, locale: String, baseDirectory: Path, translatedDirectory: Path) {
        val en = loadResources(baseDirectory, "$module values")
        val translated = loadResources(translatedDirectory, "$module values-$locale")
        val requiredEn = en.filterValues { it.translatable }
        // A translated copy of an untranslatable base entry is allowed but not required.
        val comparableTranslated = translated.filterKeys { key -> en[key]?.translatable != false }
        assertEquals(
            "$module: translatable resource names in values/*.xml must match values-$locale/*.xml",
            requiredEn.keys.sortedBy { it.toString() },
            comparableTranslated.keys.sortedBy { it.toString() }
        )

        for ((key, enEntry) in requiredEn) {
            val translatedEntry = translated.getValue(key)
            when (key.kind) {
                ResourceKind.STRING -> assertEquals(
                    "$module:$key placeholders differ between en and $locale " +
                        "(${enEntry.source.fileName} vs ${translatedEntry.source.fileName})",
                    placeholders(enEntry.text),
                    placeholders(translatedEntry.text)
                )

                ResourceKind.PLURALS -> {
                    for ((quantity, text) in enEntry.pluralItems) {
                        assertTrue(
                            "$module:$key missing $locale quantity '$quantity' " +
                                "(defined in ${enEntry.source.fileName})",
                            translatedEntry.pluralItems.containsKey(quantity)
                        )
                        assertEquals(
                            "$module:$key[$quantity] placeholders differ between en and $locale " +
                                "(${enEntry.source.fileName} vs ${translatedEntry.source.fileName})",
                            placeholders(text),
                            placeholders(translatedEntry.pluralItems.getValue(quantity))
                        )
                    }
                }
            }
        }
    }

    private fun assertParity(module: String, locale: String) {
        val root = repoRoot()
        assertParity(
            module,
            locale,
            root.resolve("$module/src/main/res/values"),
            root.resolve("$module/src/main/res/values-$locale")
        )
    }

    @Test
    fun italianMatchesBaseInMobile() = assertParity("mobile", "it")

    @Test
    fun italianMatchesBaseInWearos() = assertParity("wearos", "it")

    @Test
    fun italianMatchesBaseInShared() = assertParity("shared", "it")

    @Test
    fun paritySpansResourceFilesAndSkipsUntranslatableBaseEntries() {
        val root = Files.createTempDirectory("string-resources-parity")
        try {
            val base = Files.createDirectories(root.resolve("values"))
            val translated = Files.createDirectories(root.resolve("values-it"))
            base.resolve("strings.xml").toFile().writeText(
                """
                <resources>
                    <string name="app_name">App</string>
                    <string name="build_id" translatable="false">Build %1${'$'}s</string>
                    <string name="version_label" translatable="false">Version %1${'$'}s</string>
                </resources>
                """.trimIndent()
            )
            base.resolve("strings_localization_extra.xml").toFile().writeText(
                """
                <resources>
                    <string name="greeting">Hello %1${'$'}s</string>
                    <plurals name="item_count">
                        <item quantity="one">%1${'$'}d item</item>
                        <item quantity="other">%1${'$'}d items</item>
                    </plurals>
                </resources>
                """.trimIndent()
            )
            translated.resolve("strings_localization_extra.xml").toFile().writeText(
                """
                <resources>
                    <string name="app_name">App tradotto</string>
                    <string name="greeting">Ciao %1${'$'}s</string>
                    <string name="build_id" translatable="false">Traduzione %1${'$'}s %2${'$'}s</string>
                    <plurals name="item_count">
                        <item quantity="one">%1${'$'}d elemento</item>
                        <item quantity="many">%1${'$'}d elementi</item>
                        <item quantity="other">%1${'$'}d elementi</item>
                    </plurals>
                </resources>
                """.trimIndent()
            )

            assertParity("fixture", "it", base, translated)
        } finally {
            root.toFile().deleteRecursively()
        }
    }
}

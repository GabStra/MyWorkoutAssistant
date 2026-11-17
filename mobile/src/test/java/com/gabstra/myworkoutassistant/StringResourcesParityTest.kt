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
 * string resources: every locale must define every resource name, with the
 * same element tags, the same plural quantities, and the same set of format
 * placeholders per entry. A wrong placeholder is a runtime crash, not a build
 * failure, so it has to be caught here.
 */
class StringResourcesParityTest {

    private val formatSpec = Regex("""%(?:(\d+)\$)?[0-9.]*[sdfb]""")

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
            if (Files.exists(candidate.resolve("mobile/src/main/res/values/strings.xml"))) return candidate
            dir = candidate.parent
        }
        throw IllegalStateException("Repo root with mobile strings.xml not found from user.dir")
    }

    private fun loadStrings(path: Path): Map<String, Element> {
        val doc = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(path.toFile())
        val nodes = doc.getElementsByTagName("string")
        val out = mutableMapOf<String, Element>()
        for (i in 0 until nodes.length) {
            val e = nodes.item(i) as Element
            out[e.getAttribute("name")] = e
        }
        return out
    }

    private fun loadPlurals(path: Path): Map<String, Map<String, String>> {
        val doc = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(path.toFile())
        val nodes = doc.getElementsByTagName("plurals")
        val out = mutableMapOf<String, Map<String, String>>()
        for (i in 0 until nodes.length) {
            val p = nodes.item(i) as Element
            val items = p.getElementsByTagName("item")
            val quantities = mutableMapOf<String, String>()
            for (j in 0 until items.length) {
                val item = items.item(j) as Element
                quantities[item.getAttribute("quantity")] = item.textContent
            }
            out[p.getAttribute("name")] = quantities
        }
        return out
    }

    private fun assertParity(module: String, locale: String) {
        val root = repoRoot()
        val base = root.resolve("$module/src/main/res/values/strings.xml")
        val translated = root.resolve("$module/src/main/res/values-$locale/strings.xml")
        assertTrue("Missing $translated", Files.exists(translated))

        val en = loadStrings(base)
        val it = loadStrings(translated)
        assertEquals(
            "$module: resource names in values/strings.xml must match values-$locale/strings.xml",
            en.keys, it.keys
        )
        for ((name, enEl) in en) {
            val trEl = it.getValue(name)
            assertEquals("$module:$name tag differs between en and $locale", enEl.tagName, trEl.tagName)
            assertEquals(
                "$module:$name placeholders differ between en and $locale",
                placeholders(enEl.textContent), placeholders(trEl.textContent)
            )
        }

        val enPlurals = loadPlurals(base)
        val trPlurals = loadPlurals(translated)
        assertEquals("$module: plurals names differ", enPlurals.keys, trPlurals.keys)
        for ((name, quantities) in enPlurals) {
            val trQuantities = trPlurals.getValue(name)
            for ((quantity, text) in quantities) {
                assertTrue("$module:$name missing $locale quantity '$quantity'", trQuantities.containsKey(quantity))
                assertEquals(
                    "$module:$name[$quantity] placeholders differ between en and $locale",
                    placeholders(text), placeholders(trQuantities.getValue(quantity))
                )
            }
        }
    }

    @Test
    fun italianMatchesBaseInMobile() = assertParity("mobile", "it")

    @Test
    fun italianMatchesBaseInWearos() = assertParity("wearos", "it")
}

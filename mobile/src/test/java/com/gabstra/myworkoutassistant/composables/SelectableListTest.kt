package com.gabstra.myworkoutassistant.composables

import org.junit.Assert.assertEquals
import org.junit.Test

class SelectableListTest {

    private data class TestItem(val id: Int, val label: String)

    @Test
    fun `toggleSelectionById removes item with same id even if instance differs`() {
        val original = TestItem(1, "Item")
        val selection = listOf(original)

        // New instance with same id
        val equalInstance = original.copy(label = "Updated")

        val result = toggleSelectionById(selection, equalInstance) { it.id }

        assertEquals(emptyList<TestItem>(), result)
    }

    @Test
    fun `toggleSelectionById adds item when id not present`() {
        val selection = emptyList<TestItem>()
        val item = TestItem(1, "Item")

        val result = toggleSelectionById(selection, item) { it.id }

        assertEquals(listOf(item), result)
    }
}




package com.gabstra.myworkoutassistant.composables

import android.util.Log
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items

import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp


@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun <T> SelectableList(
    selectionMode: Boolean ,
    modifier : Modifier,
    items: List<T>,
    selection: List<T>,
    onSelectionChange: (List<T>) -> Unit,
    itemContent: @Composable (T) -> Unit
) {
    LazyColumn(
        modifier = modifier
    ) {
        items(items) { item ->
            Row(
                modifier = Modifier.padding(10.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                if (selectionMode) {
                    Checkbox(
                        checked = selection.any { it === item },
                        onCheckedChange = { checked ->
                            val newSelection =
                                if (checked) {
                                    selection + item
                                } else {
                                    selection.filter{ it !== item }
                                }
                            Log.d("test", selection.any { it === item }.toString()+ " " + checked.toString()+" " + selection.count().toString()+" " + newSelection.count().toString())
                            onSelectionChange(newSelection)
                        }
                    )
                }
                Spacer(modifier = Modifier.width(8.dp))
                itemContent(item)
            }
        }
    }
}

package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun <T> SelectableList(
    selectionMode: Boolean ,
    modifier : Modifier,
    items: List<T>,
    selection: List<T>,
    itemContent: @Composable (T) -> Unit,
) {
    Column(
        modifier = modifier
    ) {
        for(item in items){
            Row(
                modifier = Modifier.fillMaxWidth().then(if(selection.any { it === item }) Modifier.border(1.dp, MaterialTheme.colorScheme.primary) else Modifier)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(5.dp)
                ) {
                    itemContent(item)
                }
            }
        }
    }
}

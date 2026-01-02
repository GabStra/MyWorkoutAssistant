package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
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
        modifier = modifier,
        verticalArrangement =  Arrangement.spacedBy(10.dp)
    ) {
        for(item in items){
            val isSelected = selection.any { it === item }

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .then(
                        if(isSelected)
                            Modifier.border(1.dp, MaterialTheme.colorScheme.primary)
                        else Modifier
                    )
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if(isSelected)
                                Modifier.padding(5.dp)
                            else Modifier
                        )
                ) {
                    itemContent(item)
                }
            }
        }
    }
}

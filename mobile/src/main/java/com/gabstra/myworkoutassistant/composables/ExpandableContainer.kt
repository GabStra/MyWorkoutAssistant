package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun ExpandableContainer(
    modifier : Modifier = Modifier,
    titleModifier: Modifier = Modifier,
    isExpandable:Boolean = true,
    isOpen: Boolean = false,
    title: @Composable (modifier: Modifier) -> Unit,
    subContent : @Composable () -> Unit = {},
    collapsedContent: @Composable () -> Unit = {},
    content: @Composable () -> Unit,
    onOpen: () -> Unit = {},
    onClose: () -> Unit = {},
){
    var openStatus by rememberSaveable {
        mutableStateOf(isOpen)
    }

    Column(
        modifier = modifier,
    ){
        val toggle = {
            openStatus = !openStatus
            if (openStatus) onOpen() else onClose()
        }
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .height(IntrinsicSize.Min)
                .then(if (isExpandable) Modifier.clickable(onClick = toggle) else Modifier)
                .padding(vertical = 4.dp),
        ){
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxHeight()
                    .then(titleModifier),
                contentAlignment = Alignment.CenterStart
            ) {
                title(Modifier.fillMaxWidth())
            }
            if(isExpandable){
                Icon(
                    modifier = Modifier.padding(horizontal = 14.dp),
                    imageVector = if (openStatus) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                    contentDescription = if (openStatus) "Collapse" else "Expand",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        subContent()
        if (!openStatus) {
            collapsedContent()
        }
        if(openStatus){
            Box{
                content()
            }
        }
    }
}

# Lumiverse Macro Reference (LLM Digest)

Generated from `/path/to/Lumiverse` (runtime_registry) at 2026-07-17T04:36:26.898528+00:00.
Built-in macros: **235**.

This catalog is sourced from the backend macro registry when available, so aliases and descriptions track the actual runtime implementation.

## Character

### `{{charCreator}}`
- **Purpose:** Character creator name
- **Returns:** string
- **Usage:** `{{charCreator}}`

### `{{charCreatorNotes}}`
- **Aliases:** `{{creatorNotes}}`
- **Purpose:** Character creator notes
- **Returns:** string
- **Usage:** `{{charCreatorNotes}}`

### `{{charDepthPrompt}}`
- **Aliases:** `{{depth_prompt}}`
- **Purpose:** Character depth prompt (extension)
- **Returns:** string
- **Usage:** `{{charDepthPrompt}}`

### `{{charGroupFocusedDescription}}`
- **Aliases:** `{{charFocusedDescription}}`, `{{char_group_focused_description}}`
- **Purpose:** Focused group character description
- **Returns:** string
- **Usage:** `{{charGroupFocusedDescription}}`

### `{{charGroupFocusedPersonality}}`
- **Aliases:** `{{charFocusedPersonality}}`, `{{char_group_focused_personality}}`
- **Purpose:** Focused group character personality
- **Returns:** string
- **Usage:** `{{charGroupFocusedPersonality}}`

### `{{charPostHistoryInstructions}}`
- **Aliases:** `{{charInstruction}}`, `{{jailbreak}}`, `{{charJailbreak}}`
- **Purpose:** Character jailbreak/post-history instructions
- **Returns:** string
- **Usage:** `{{charPostHistoryInstructions}}`

### `{{charTags}}`
- **Aliases:** `{{characterTags}}`, `{{char_tags}}`, `{{tags}}`
- **Purpose:** Comma-separated list of the character's tags.
- **Returns:** string
- **Usage:** `{{charTags}}`

### `{{charVersion}}`
- **Purpose:** Character card version
- **Returns:** string
- **Usage:** `{{charVersion}}`

### `{{description}}`
- **Aliases:** `{{charDescription}}`
- **Purpose:** Character description
- **Returns:** string
- **Usage:** `{{description}}`

### `{{firstMessage}}`
- **Aliases:** `{{firstMes}}`, `{{first_message}}`
- **Purpose:** Character's first message / greeting
- **Returns:** string
- **Usage:** `{{firstMessage}}`

### `{{hasTag::tag}}`
- **Aliases:** `{{charTag::tag}}`, `{{char_tag::tag}}`, `{{has_tag::tag}}`, `{{tagged::tag}}`
- **Purpose:** Check whether the character has a specific tag (case-insensitive).
- **Args:** tag — Tag to check (case-insensitive)
- **Returns:** boolean
- **Usage:** `{{hasTag::tag}}`

### `{{mesExamples}}`
- **Aliases:** `{{mes_examples}}`, `{{exampleMessages}}`
- **Purpose:** Character example dialogue messages
- **Returns:** string
- **Usage:** `{{mesExamples}}`

### `{{mesExamplesRaw}}`
- **Purpose:** Raw example dialogue (unprocessed)
- **Returns:** string
- **Usage:** `{{mesExamplesRaw}}`

### `{{obj}}`
- **Aliases:** `{{objectivePronoun}}`, `{{personaObjectivePronoun}}`
- **Purpose:** Persona objective pronoun
- **Returns:** string
- **Usage:** `{{obj}}`

### `{{original}}`
- **Purpose:** Alias for character description (original card text)
- **Returns:** string
- **Usage:** `{{original}}`

### `{{persona}}`
- **Aliases:** `{{userPersona}}`
- **Purpose:** User persona description
- **Returns:** string
- **Usage:** `{{persona}}`

### `{{personality}}`
- **Aliases:** `{{charPersonality}}`
- **Purpose:** Character personality
- **Returns:** string
- **Usage:** `{{personality}}`

### `{{poss}}`
- **Aliases:** `{{possessivePronoun}}`, `{{personaPossessivePronoun}}`
- **Purpose:** Persona possessive pronoun
- **Returns:** string
- **Usage:** `{{poss}}`

### `{{randomTag}}`
- **Aliases:** `{{random_tag}}`, `{{randomCharTag}}`
- **Purpose:** Random tag from the character card.
- **Returns:** string
- **Usage:** `{{randomTag}}`

### `{{scenario}}`
- **Aliases:** `{{charScenario}}`
- **Purpose:** Character scenario
- **Returns:** string
- **Usage:** `{{scenario}}`

### `{{sub}}`
- **Aliases:** `{{subjectivePronoun}}`, `{{personaSubjectivePronoun}}`
- **Purpose:** Persona subjective pronoun
- **Returns:** string
- **Usage:** `{{sub}}`

### `{{system}}`
- **Aliases:** `{{charPrompt}}`, `{{charSystem}}`
- **Purpose:** Character system prompt
- **Returns:** string
- **Usage:** `{{system}}`

### `{{tag::index}}`
- **Aliases:** `{{tagAt::index}}`, `{{tag_at::index}}`, `{{charTagAt::index}}`, `{{nthTag::index}}`
- **Purpose:** Character tag at a 0-based index. Negative indexes count from the end.
- **Args:** index — 0-based index; negative counts from the end
- **Returns:** string
- **Usage:** `{{tag::index}}`

### `{{tagCount}}`
- **Aliases:** `{{tag_count}}`, `{{tags_count}}`, `{{numTags}}`, `{{charTagCount}}`
- **Purpose:** Number of tags on the character card.
- **Returns:** integer
- **Usage:** `{{tagCount}}`

## Chat

### `{{chatId}}`
- **Aliases:** `{{chat_id}}`
- **Purpose:** Current chat ID
- **Returns:** string
- **Usage:** `{{chatId}}`

### `{{currentSwipeId}}`
- **Purpose:** Index of the currently active swipe
- **Returns:** integer
- **Usage:** `{{currentSwipeId}}`

### `{{firstDisplayedMessageId}}`
- **Purpose:** Index of the first displayed message (same as firstIncludedMessageId)
- **Returns:** integer
- **Usage:** `{{firstDisplayedMessageId}}`

### `{{firstIncludedMessageId}}`
- **Purpose:** Index of the first message included in the prompt
- **Returns:** integer
- **Usage:** `{{firstIncludedMessageId}}`

### `{{lastCharMessage}}`
- **Aliases:** `{{last_char_message}}`, `{{lastBotMessage}}`
- **Purpose:** Content of the last character message
- **Returns:** string
- **Usage:** `{{lastCharMessage}}`

### `{{lastMessage}}`
- **Aliases:** `{{last_message}}`
- **Purpose:** Content of the last chat message
- **Returns:** string
- **Usage:** `{{lastMessage}}`

### `{{lastMessageId}}`
- **Aliases:** `{{last_message_id}}`
- **Purpose:** Index of the last message in chat
- **Returns:** integer
- **Usage:** `{{lastMessageId}}`

### `{{lastMessageName}}`
- **Purpose:** Name of the sender of the last message
- **Returns:** string
- **Usage:** `{{lastMessageName}}`

### `{{lastSwipeId}}`
- **Purpose:** Index of the last swipe on the last message
- **Returns:** integer
- **Usage:** `{{lastSwipeId}}`

### `{{lastUserMessage}}`
- **Aliases:** `{{last_user_message}}`
- **Purpose:** Content of the last user message
- **Returns:** string
- **Usage:** `{{lastUserMessage}}`

### `{{messageCount}}`
- **Aliases:** `{{message_count}}`, `{{messagecount}}`
- **Purpose:** Total number of messages in chat
- **Returns:** integer
- **Usage:** `{{messageCount}}`

### `{{rejectedSwipe}}`
- **Aliases:** `{{rejectedGeneration}}`, `{{regeneratedMessage}}`
- **Purpose:** Content of the regenerate/swipe target before the new swipe was staged
- **Returns:** string
- **Usage:** `{{rejectedSwipe}}`

## Chat Utilities

### `{{chatAge}}`
- **Aliases:** `{{chat_age}}`
- **Purpose:** Human-readable time since the chat was created
- **Returns:** string
- **Usage:** `{{chatAge}}`

### `{{counter::name}}`
- **Purpose:** Increment a named counter (local variable) and return the new value
- **Args:** name — Counter name
- **Returns:** integer
- **Usage:** `{{counter::name}}`

### `{{messageAt::index}}`
- **Aliases:** `{{message_at::index}}`, `{{msgAt::index}}`
- **Purpose:** Get message content at a specific index (0-based). Negative indexes count from end.
- **Args:** index — Message index (0-based, negative counts from end)
- **Returns:** string
- **Usage:** `{{messageAt::index}}`

### `{{messagesBy::name::[count]}}`
- **Aliases:** `{{messages_by::name::[count]}}`, `{{msgBy::name::[count]}}`
- **Purpose:** Get last N messages from a specific speaker, most recent first
- **Args:** name — Speaker name; [count] — Max messages (default 3)
- **Returns:** string
- **Usage:** `{{messagesBy::name::[count]}}`

### `{{rcounter::name::[reset]}}`
- **Purpose:** Increment a render-scoped counter and return the new value. The counter lives on env.extra and resets at the start of every prompt build — it is never written to env.variables.local and therefore never persists to chat metadata. Use 'reset' as the second arg to zero the counter.
- **Args:** name — Counter name; [reset] — Pass 'reset' to zero the counter
- **Returns:** integer
- **Usage:** `{{rcounter::name::[reset]}}`

### `{{toggle::name}}`
- **Purpose:** Toggle a named boolean (local variable) and return the new value
- **Args:** name — Toggle name
- **Returns:** boolean
- **Usage:** `{{toggle::name}}`

## Core

### `{{//}}`
- **Purpose:** Inline comment shorthand — resolves to empty string
- **Returns:** string
- **Usage:** `{{//}}`

### `{{banned}}`
- **Purpose:** Placeholder for banned tokens — resolves to empty
- **Returns:** string
- **Usage:** `{{banned}}`

### `{{comment}}`
- **Aliases:** `{{note}}`
- **Purpose:** Comment — resolves to empty string, content is ignored
- **Returns:** string
- **Usage:** `{{comment}}`

### `{{else}}`
- **Purpose:** Else branch for if blocks
- **Returns:** string
- **Usage:** `{{else}}`

### `{{elseif}}`
- **Aliases:** `{{elif}}`
- **Purpose:** Else-if marker for {{if}} blocks
- **Returns:** string
- **Usage:** `{{elseif}}`

### `{{if::condition}}...{{else}}...{{/if}}`
- **Purpose:** Conditional block.
- **Returns:** string
- **Usage:** `{{if::condition}}...{{else}}...{{/if}}`

### `{{input}}`
- **Purpose:** Resolves to the raw user input (last user message)
- **Returns:** string
- **Usage:** `{{input}}`

### `{{newline}}`
- **Aliases:** `{{nl}}`, `{{n}}`
- **Purpose:** Inserts a literal newline character
- **Returns:** string
- **Usage:** `{{newline}}`

### `{{noop}}`
- **Purpose:** No operation — resolves to empty string
- **Returns:** string
- **Usage:** `{{noop}}`

### `{{outlet::name}}`
- **Purpose:** Resolve an activated world-info outlet by name
- **Args:** name — Outlet name configured on a world-info entry
- **Returns:** string
- **Usage:** `{{outlet::name}}`

### `{{reverse::text}}`
- **Purpose:** Reverse a string
- **Args:** text — Text to reverse
- **Returns:** string
- **Usage:** `{{reverse::text}}`

### `{{space}}`
- **Purpose:** Inserts a literal space character
- **Returns:** string
- **Usage:** `{{space}}`

### `{{trim}}...{{/trim}}`
- **Purpose:** Trim whitespace from scoped content or surrounding whitespace in post mode
- **Returns:** string
- **Usage:** `{{trim}}...{{/trim}}`

### `{{unless}}`
- **Purpose:** Inverse conditional block.
- **Returns:** string
- **Usage:** `{{unless}}`

### `{{wi_marker}}`
- **Purpose:** Resolve all activated world-info entries set to 'At Marker' position, joined by double newlines
- **Returns:** string
- **Usage:** `{{wi_marker}}`

## Formatting

### `{{bullets::item1::item2}}`
- **Purpose:** Format items as a bulleted list. Args: items. Scoped: splits body on newlines.
- **Returns:** string
- **Usage:** `{{bullets::item1::item2}}`

### `{{numbered::item1::item2}}`
- **Aliases:** `{{ol::item1::item2}}`, `{{enumerate::item1::item2}}`
- **Purpose:** Format items as a numbered list. Args: items. Scoped: splits body on newlines.
- **Returns:** string
- **Usage:** `{{numbered::item1::item2}}`

## Iteration

### `{{every::list::var::[delimiter]}}...{{/every}}`
- **Aliases:** `{{all::list::var::[delimiter]}}...{{/all}}`
- **Purpose:** 'true' if every list item's body (an {{if}}-style condition) is truthy, else ''. Vacuously 'true' for an empty list. Short-circuits.
- **Returns:** boolean
- **Usage:** `{{every::list::var::[delimiter]}}...{{/every}}`

### `{{filter::list::var::[delimiter]}}...{{/filter}}`
- **Aliases:** `{{where::list::var::[delimiter]}}...{{/where}}`
- **Purpose:** Keep list items whose body (an {{if}}-style condition) is truthy; returns a comma-separated list.
- **Returns:** string
- **Usage:** `{{filter::list::var::[delimiter]}}...{{/filter}}`

### `{{foreach::list::[var]::[delimiter]}}...{{/foreach}}`
- **Aliases:** `{{each::list::[var]::[delimiter]}}...{{/each}}`, `{{for_each::list::[var]::[delimiter]}}...{{/for_each}}`
- **Purpose:** Iterate over a delimited list, resolving the body once per item.
- **Returns:** string
- **Usage:** `{{foreach::list::[var]::[delimiter]}}...{{/foreach}}`

### `{{foreachChatVar::prefix::[var]}}...{{/foreachChatVar}}`
- **Aliases:** `{{for_each_chat_var::prefix::[var]}}...{{/for_each_chat_var}}`
- **Purpose:** Iterate chat variables whose name starts with a prefix (alphabetical order). Bindings: {{.item}} (name after the prefix), {{.item_key}} (full name), {{.item_value}}, plus index/number/count/first/last.
- **Returns:** string
- **Usage:** `{{foreachChatVar::prefix::[var]}}...{{/foreachChatVar}}`

### `{{foreachGlobalVar::prefix::[var]}}...{{/foreachGlobalVar}}`
- **Aliases:** `{{foreachGvar::prefix::[var]}}...{{/foreachGvar}}`, `{{for_each_global_var::prefix::[var]}}...{{/for_each_global_var}}`
- **Purpose:** Iterate global variables whose name starts with a prefix (alphabetical order). Bindings: {{.item}} (name after the prefix), {{.item_key}} (full name), {{.item_value}}, plus index/number/count/first/last.
- **Returns:** string
- **Usage:** `{{foreachGlobalVar::prefix::[var]}}...{{/foreachGlobalVar}}`

### `{{foreachMessage::[count_or_var]::[var]}}...{{/foreachMessage}}`
- **Aliases:** `{{for_each_message::[count_or_var]::[var]}}...{{/for_each_message}}`
- **Purpose:** Iterate over chat history, resolving the body once per message. Optional first arg: a number (iterate the last N messages) or a loop variable name (default 'msg'). Bindings: {{.msg}}, {{.msg_name}}, {{.msg_is_user}}, plus the usual index/number/count/first/last.
- **Returns:** string
- **Usage:** `{{foreachMessage::[count_or_var]::[var]}}...{{/foreachMessage}}`

### `{{foreachVar::prefix::[var]}}...{{/foreachVar}}`
- **Aliases:** `{{for_each_var::prefix::[var]}}...{{/for_each_var}}`
- **Purpose:** Iterate local variables whose name starts with a prefix (alphabetical order). Bindings: {{.item}} (name after the prefix), {{.item_key}} (full name), {{.item_value}}, plus index/number/count/first/last.
- **Returns:** string
- **Usage:** `{{foreachVar::prefix::[var]}}...{{/foreachVar}}`

### `{{map}}`
- **Aliases:** `{{collect}}`
- **Purpose:** Transform each item in a delimited list with a scoped body.
- **Returns:** string
- **Usage:** `{{map}}`

### `{{range::start_or_end::[end]::[step]}}`
- **Purpose:** Generate a numeric sequence as a comma-separated list. {{range::5}} → 1, 2, 3, 4, 5. {{range::start::end}} (inclusive) or {{range::start::end::step}}. Counts down when start > end.
- **Args:** start_or_end — End (1-based) with one arg, or start with two+; [end] — End value (inclusive); [step] — Step size (default 1, or -1 counting down)
- **Returns:** string
- **Usage:** `{{range::start_or_end::[end]::[step]}}`

### `{{some::list::var::[delimiter]}}...{{/some}}`
- **Aliases:** `{{any::list::var::[delimiter]}}...{{/any}}`
- **Purpose:** 'true' if any list item's body (an {{if}}-style condition) is truthy, else ''. Short-circuits.
- **Returns:** boolean
- **Usage:** `{{some::list::var::[delimiter]}}...{{/some}}`

## Lists

### `{{avg::list}}`
- **Aliases:** `{{mean::list}}`, `{{average::list}}`
- **Purpose:** Average (mean) of the numeric items of a list. Empty when there are no numbers.
- **Args:** list — Comma-separated list of numbers
- **Returns:** number
- **Usage:** `{{avg::list}}`

### `{{count::list}}`
- **Aliases:** `{{listLength::list}}`, `{{list_count::list}}`
- **Purpose:** Number of items in a comma-separated list (blanks ignored).
- **Args:** list — Comma-separated list
- **Returns:** integer
- **Usage:** `{{count::list}}`

### `{{first::list}}`
- **Purpose:** First item of a list (empty if the list is empty).
- **Args:** list — Comma-separated list
- **Returns:** string
- **Usage:** `{{first::list}}`

### `{{includes::list::item}}`
- **Aliases:** `{{contains::list::item}}`, `{{inList::list::item}}`
- **Purpose:** 'true' if the list contains the item (whole-item, case-sensitive match), else ''. Usable as a condition.
- **Args:** list — Comma-separated list; item — Item to look for
- **Returns:** boolean
- **Usage:** `{{includes::list::item}}`

### `{{last::list}}`
- **Purpose:** Last item of a list (empty if the list is empty).
- **Args:** list — Comma-separated list
- **Returns:** string
- **Usage:** `{{last::list}}`

### `{{listMax::list}}`
- **Aliases:** `{{list_max::list}}`
- **Purpose:** Largest numeric item of a list. Empty when there are no numbers.
- **Args:** list — Comma-separated list of numbers
- **Returns:** number
- **Usage:** `{{listMax::list}}`

### `{{listMin::list}}`
- **Aliases:** `{{list_min::list}}`
- **Purpose:** Smallest numeric item of a list. Empty when there are no numbers.
- **Args:** list — Comma-separated list of numbers
- **Returns:** number
- **Usage:** `{{listMin::list}}`

### `{{nth::list::index}}`
- **Aliases:** `{{at::list::index}}`
- **Purpose:** Item at a 0-based index (negative counts from the end). Empty if out of range.
- **Args:** list — Comma-separated list; index — 0-based index; negative counts from the end
- **Returns:** string
- **Usage:** `{{nth::list::index}}`

### `{{reverseList::list}}`
- **Aliases:** `{{reverse_list::list}}`
- **Purpose:** Reverse the order of a list's items.
- **Args:** list — Comma-separated list
- **Returns:** string
- **Usage:** `{{reverseList::list}}`

### `{{shuffle::list}}`
- **Purpose:** Randomly reorder a list's items.
- **Args:** list — Comma-separated list
- **Returns:** string
- **Usage:** `{{shuffle::list}}`

### `{{slice::list::start::[end]}}`
- **Purpose:** Sublist from start to end (end exclusive, optional). Negative indices count from the end. {{slice::list::-3}} → last 3 items.
- **Args:** list — Comma-separated list; start — Start index (0-based; negative from end); [end] — End index, exclusive (default: through end)
- **Returns:** string
- **Usage:** `{{slice::list::start::[end]}}`

### `{{sort::list::[direction]}}`
- **Purpose:** Sort a list. Numeric when every item is a number, otherwise alphabetical. Pass 'desc' as the second argument to reverse the order.
- **Args:** list — Comma-separated list; [direction] — 'asc' (default) or 'desc'
- **Returns:** string
- **Usage:** `{{sort::list::[direction]}}`

### `{{sum::list}}`
- **Purpose:** Sum the numeric items of a list (non-numbers ignored). 0 for an empty list.
- **Args:** list — Comma-separated list of numbers
- **Returns:** number
- **Usage:** `{{sum::list}}`

### `{{take::list::n}}`
- **Purpose:** First N items of a list (negative N takes the last |N| items).
- **Args:** list — Comma-separated list; n — How many items (negative counts from the end)
- **Returns:** string
- **Usage:** `{{take::list::n}}`

### `{{unique::list}}`
- **Aliases:** `{{dedupe::list}}`, `{{distinct::list}}`
- **Purpose:** Remove duplicate items, keeping the first occurrence's order.
- **Args:** list — Comma-separated list
- **Returns:** string
- **Usage:** `{{unique::list}}`

## Logic

### `{{and::item1::item2}}`
- **Purpose:** Logical AND — returns 'true' if all arguments are truthy, else ''
- **Returns:** boolean
- **Usage:** `{{and::item1::item2}}`

### `{{blank::value}}`
- **Aliases:** `{{isBlank::value}}`
- **Purpose:** Returns 'true' when the value is empty or whitespace-only
- **Args:** value — Value to test
- **Returns:** boolean
- **Usage:** `{{blank::value}}`

### `{{case}}`
- **Purpose:** Case block marker for scoped {{switch}} blocks
- **Returns:** string
- **Usage:** `{{case}}`

### `{{default::value::fallback}}`
- **Aliases:** `{{fallback::value::fallback}}`, `{{coalesce::value::fallback}}`
- **Purpose:** Return the first truthy value, or the fallback
- **Args:** value — Primary value; fallback — Fallback if value is falsy
- **Returns:** string
- **Usage:** `{{default::value::fallback}}`

### `{{empty::value}}`
- **Aliases:** `{{isEmpty::value}}`
- **Purpose:** Returns 'true' when the value is exactly empty
- **Args:** value — Value to test
- **Returns:** boolean
- **Usage:** `{{empty::value}}`

### `{{endsWith::text::suffix}}`
- **Aliases:** `{{ends_with::text::suffix}}`
- **Purpose:** Returns 'true' when text ends with suffix
- **Args:** text — Text to test; suffix — Suffix
- **Returns:** boolean
- **Usage:** `{{endsWith::text::suffix}}`

### `{{eq::a::b}}`
- **Purpose:** Equality check — returns 'true' if a == b (numeric-aware)
- **Args:** a — Left value; b — Right value
- **Returns:** boolean
- **Usage:** `{{eq::a::b}}`

### `{{gt::a::b}}`
- **Purpose:** Greater-than check — returns 'true' if a > b
- **Args:** a — Left value; b — Right value
- **Returns:** boolean
- **Usage:** `{{gt::a::b}}`

### `{{gte::a::b}}`
- **Purpose:** Greater-than-or-equal check — returns 'true' if a >= b
- **Args:** a — Left value; b — Right value
- **Returns:** boolean
- **Usage:** `{{gte::a::b}}`

### `{{integer::value}}`
- **Aliases:** `{{isInteger::value}}`, `{{int::value}}`
- **Purpose:** Returns 'true' when the value is an integer
- **Args:** value — Value to test
- **Returns:** boolean
- **Usage:** `{{integer::value}}`

### `{{lt::a::b}}`
- **Purpose:** Less-than check — returns 'true' if a < b
- **Args:** a — Left value; b — Right value
- **Returns:** boolean
- **Usage:** `{{lt::a::b}}`

### `{{lte::a::b}}`
- **Purpose:** Less-than-or-equal check — returns 'true' if a <= b
- **Args:** a — Left value; b — Right value
- **Returns:** boolean
- **Usage:** `{{lte::a::b}}`

### `{{matches::text::pattern::[flags]}}`
- **Purpose:** Returns 'true' when text matches a regular expression
- **Args:** text — Text to test; pattern — Regular expression pattern; [flags] — Regex flags
- **Returns:** boolean
- **Usage:** `{{matches::text::pattern::[flags]}}`

### `{{ne::a::b}}`
- **Purpose:** Inequality check — returns 'true' if a != b
- **Args:** a — Left value; b — Right value
- **Returns:** boolean
- **Usage:** `{{ne::a::b}}`

### `{{not::value}}`
- **Purpose:** Logical NOT — returns 'true' if value is falsy, else ''
- **Args:** value — Value to negate
- **Returns:** boolean
- **Usage:** `{{not::value}}`

### `{{number::value}}`
- **Aliases:** `{{isNumber::value}}`, `{{numeric::value}}`
- **Purpose:** Returns 'true' when the value is a finite number
- **Args:** value — Value to test
- **Returns:** boolean
- **Usage:** `{{number::value}}`

### `{{or::item1::item2}}`
- **Purpose:** Logical OR — returns 'true' if any argument is truthy, else ''
- **Returns:** boolean
- **Usage:** `{{or::item1::item2}}`

### `{{startsWith::text::prefix}}`
- **Aliases:** `{{starts_with::text::prefix}}`
- **Purpose:** Returns 'true' when text starts with prefix
- **Args:** text — Text to test; prefix — Prefix
- **Returns:** boolean
- **Usage:** `{{startsWith::text::prefix}}`

### `{{switch::item1::item2}}`
- **Purpose:** Multi-branch conditional. {{switch::value::case1::result1::case2::result2::default}}
- **Returns:** string
- **Usage:** `{{switch::item1::item2}}`

## Loom

### `{{loomContinuePrompt}}`
- **Purpose:** Continuation instructions when Sovereign Hand is enabled and character was last speaker. Empty otherwise.
- **Returns:** string
- **Usage:** `{{loomContinuePrompt}}`

### `{{loomLastCharMessage}}`
- **Purpose:** Content of last character/assistant message (alias for lastCharMessage).
- **Returns:** string
- **Usage:** `{{loomLastCharMessage}}`

### `{{loomLastMessageName}}`
- **Purpose:** Name of whoever sent the last message (alias for lastMessageName).
- **Returns:** string
- **Usage:** `{{loomLastMessageName}}`

### `{{loomLastUserMessage}}`
- **Purpose:** Last user message content (alias for lastUserMessage).
- **Returns:** string
- **Usage:** `{{loomLastUserMessage}}`

### `{{loomSovHand}}`
- **Purpose:** Full Sovereign Hand co-pilot mode prompt. Includes user directive interpretation and continuation logic.
- **Returns:** string
- **Usage:** `{{loomSovHand}}`

### `{{loomSovHandActive}}`
- **Purpose:** Returns 'yes' or 'no' for Sovereign Hand mode. Conditional compatible.
- **Returns:** boolean
- **Usage:** `{{loomSovHandActive}}`

### `{{loomSummary}}`
- **Purpose:** Stored Loom summary from chat metadata (from most recent <loom_sum> block).
- **Returns:** string
- **Usage:** `{{loomSummary}}`

### `{{loomSummaryPrompt}}`
- **Purpose:** Loom summarization directive prompt with section structure.
- **Returns:** string
- **Usage:** `{{loomSummaryPrompt}}`

## Lumia

### `{{loomCouncilResult::variable_name}}`
- **Purpose:** Named council tool result variable. Arg: variable_name (alphanumeric).
- **Args:** variable_name — Alphanumeric result variable name
- **Returns:** string
- **Usage:** `{{loomCouncilResult::variable_name}}`

### `{{loomRetrofits::[property]}}`
- **Purpose:** All selected Loom retrofit prompts. Arg 'len' returns count.
- **Args:** [property] — 'len' to get count
- **Returns:** string
- **Usage:** `{{loomRetrofits::[property]}}`

### `{{loomStyle::[property]}}`
- **Purpose:** Selected Loom narrative style content. Arg 'len' returns count.
- **Args:** [property] — 'len' to get count
- **Returns:** string
- **Usage:** `{{loomStyle::[property]}}`

### `{{loomUtils::[property]}}`
- **Purpose:** All selected Loom utility prompts. Arg 'len' returns count.
- **Args:** [property] — 'len' to get count
- **Returns:** string
- **Usage:** `{{loomUtils::[property]}}`

### `{{lumiaBehavior::[property]}}`
- **Purpose:** All selected behavioral traits. Adapts to Council mode. Arg 'len' returns count.
- **Args:** [property] — 'len' to get count
- **Returns:** string
- **Usage:** `{{lumiaBehavior::[property]}}`

### `{{lumiaCouncilDeliberation}}`
- **Purpose:** Council tool execution results and deliberation instructions. Empty when no council results are available.
- **Returns:** string
- **Usage:** `{{lumiaCouncilDeliberation}}`

### `{{lumiaCouncilInst}}`
- **Purpose:** Council mode instruction prompt with member names. Empty when council disabled.
- **Returns:** string
- **Usage:** `{{lumiaCouncilInst}}`

### `{{lumiaCouncilModeActive}}`
- **Purpose:** Returns 'yes' or 'no' for council mode status. Conditional compatible.
- **Returns:** boolean
- **Usage:** `{{lumiaCouncilModeActive}}`

### `{{lumiaCouncilToolsActive}}`
- **Purpose:** Returns 'yes' or 'no' for council tools status. Conditional compatible.
- **Returns:** boolean
- **Usage:** `{{lumiaCouncilToolsActive}}`

### `{{lumiaCouncilToolsList}}`
- **Purpose:** Lists configured council tools with member attribution.
- **Returns:** string
- **Usage:** `{{lumiaCouncilToolsList}}`

### `{{lumiaDef::[property]}}`
- **Purpose:** Selected Lumia physical definition. Adapts to Council/Chimera modes. Arg 'len' returns count.
- **Args:** [property] — 'len' to get count
- **Returns:** string
- **Usage:** `{{lumiaDef::[property]}}`

### `{{lumiaMessageCount}}`
- **Purpose:** Current chat message count (alias for messageCount).
- **Returns:** integer
- **Usage:** `{{lumiaMessageCount}}`

### `{{lumiaOOC}}`
- **Purpose:** OOC commentary prompt. Adapts to Council mode and OOC style (normal/IRC).
- **Returns:** string
- **Usage:** `{{lumiaOOC}}`

### `{{lumiaOOCErotic}}`
- **Purpose:** Sexually charged OOC prompt (Mirror & Synapse). Adapts to Council mode.
- **Returns:** string
- **Usage:** `{{lumiaOOCErotic}}`

### `{{lumiaOOCEroticBleed}}`
- **Purpose:** Mid-narrative erotic OOC rupture prompt. Adapts to Council mode.
- **Returns:** string
- **Usage:** `{{lumiaOOCEroticBleed}}`

### `{{lumiaOOCTrigger}}`
- **Purpose:** OOC trigger countdown or activation message based on message count and interval.
- **Returns:** string
- **Usage:** `{{lumiaOOCTrigger}}`

### `{{lumiaPersonality::[property]}}`
- **Purpose:** All selected personality traits. Adapts to Council mode. Arg 'len' returns count.
- **Args:** [property] — 'len' to get count
- **Returns:** string
- **Usage:** `{{lumiaPersonality::[property]}}`

### `{{lumiaQuirks}}`
- **Aliases:** `{{lumiaCouncilQuirks}}`
- **Purpose:** Formatted behavioral quirks. Adapts header for Council/Chimera/single modes.
- **Returns:** string
- **Usage:** `{{lumiaQuirks}}`

### `{{lumiaSelf::form}}`
- **Purpose:** Self-address pronouns. Arg: 1=possessive det (my/our), 2=possessive pn (mine/ours), 3=object (me/us), 4=subject (I/we).
- **Args:** form — 1, 2, 3, or 4
- **Returns:** string
- **Usage:** `{{lumiaSelf::form}}`

### `{{lumiaStateSynthesis}}`
- **Purpose:** Smart synthesis prompt — 'Council Sound-Off' or 'State Synthesis' depending on mode. Empty if not applicable.
- **Returns:** string
- **Usage:** `{{lumiaStateSynthesis}}`

### `{{randomLumia::[property]}}`
- **Purpose:** Random Lumia from all loaded packs. Optional arg: name, phys, pers, behav.
- **Args:** [property] — name, phys, pers, or behav
- **Returns:** string
- **Usage:** `{{randomLumia::[property]}}`

## Math

### `{{abs::value}}`
- **Purpose:** Absolute value of a number
- **Args:** value — Number
- **Returns:** number
- **Usage:** `{{abs::value}}`

### `{{calc::expression}}`
- **Aliases:** `{{math::expression}}`, `{{evaluate::expression}}`
- **Purpose:** Evaluate a math expression (+ - * / % with parentheses)
- **Args:** expression — Math expression to evaluate
- **Returns:** number
- **Usage:** `{{calc::expression}}`

### `{{ceil::value}}`
- **Purpose:** Round up to nearest integer
- **Args:** value — Number to ceil
- **Returns:** integer
- **Usage:** `{{ceil::value}}`

### `{{clamp::value::min::max}}`
- **Purpose:** Clamp a value between min and max
- **Args:** value — Value to clamp; min — Minimum bound; max — Maximum bound
- **Returns:** number
- **Usage:** `{{clamp::value::min::max}}`

### `{{floor::value}}`
- **Purpose:** Round down to nearest integer
- **Args:** value — Number to floor
- **Returns:** integer
- **Usage:** `{{floor::value}}`

### `{{max::item1::item2}}`
- **Purpose:** Return the largest of two or more numbers
- **Returns:** number
- **Usage:** `{{max::item1::item2}}`

### `{{min::item1::item2}}`
- **Purpose:** Return the smallest of two or more numbers
- **Returns:** number
- **Usage:** `{{min::item1::item2}}`

### `{{mod::a::b}}`
- **Purpose:** Modulo (remainder of division)
- **Args:** a — Dividend; b — Divisor
- **Returns:** number
- **Usage:** `{{mod::a::b}}`

### `{{round::value::[decimals]}}`
- **Purpose:** Round a number to N decimal places (default 0)
- **Args:** value — Number to round; [decimals] — Decimal places (default 0)
- **Returns:** number
- **Usage:** `{{round::value::[decimals]}}`

## Memory

### `{{arc}}`
- **Purpose:** Current narrative arc summary from the Memory Cortex consolidation layer.
- **Usage:** `{{arc}}`

### `{{characterColors}}`
- **Purpose:** Font color attributions per character from the Memory Cortex. Lists each character with their speech, thought, and narration colors. Use in presets to avoid manually specifying color instructions.
- **Usage:** `{{characterColors}}`

### `{{cortexActive}}`
- **Purpose:** Returns 'yes' if the Memory Cortex is enabled and produced results, 'no' otherwise.
- **Usage:** `{{cortexActive}}`

### `{{databank::[count]}}`
- **Aliases:** `{{databankMemory::[count]}}`, `{{documents::[count]}}`, `{{knowledgeBank::[count]}}`
- **Purpose:** Retrieved databank document chunks relevant to the current context.
- **Args:** [count] — Override number of chunks to include
- **Usage:** `{{databank::[count]}}`

### `{{databankActive}}`
- **Purpose:** Returns 'yes' if databank is enabled and chunks were retrieved, 'no' otherwise.
- **Usage:** `{{databankActive}}`

### `{{databankCount}}`
- **Purpose:** Number of databank chunks retrieved this generation.
- **Usage:** `{{databankCount}}`

### `{{databankRaw::[count]}}`
- **Purpose:** Raw databank chunks joined by separator, without header wrapper.
- **Args:** [count] — Override number of chunks to include
- **Usage:** `{{databankRaw::[count]}}`

### `{{entities::[count]}}`
- **Purpose:** Active entity snapshots with facts and relationships from the Memory Cortex.
- **Args:** [count] — Max entities to include
- **Usage:** `{{entities::[count]}}`

### `{{entityCount}}`
- **Purpose:** Number of entities active in the current retrieval context.
- **Usage:** `{{entityCount}}`

### `{{entityFacts::entityName}}`
- **Purpose:** Key facts about a named entity.
- **Args:** entityName — Name of the entity to look up
- **Usage:** `{{entityFacts::entityName}}`

### `{{memories::[count]}}`
- **Aliases:** `{{longTermMemory::[count]}}`, `{{chatMemory::[count]}}`, `{{ltm::[count]}}`
- **Purpose:** Retrieved long-term memory chunks, formatted with header template.
- **Args:** [count] — Override number of chunks to include
- **Usage:** `{{memories::[count]}}`

### `{{memoriesActive}}`
- **Purpose:** Returns 'yes' if memories are enabled and chunks were retrieved, 'no' otherwise.
- **Usage:** `{{memoriesActive}}`

### `{{memoriesCount}}`
- **Purpose:** Number of memory chunks retrieved this generation.
- **Usage:** `{{memoriesCount}}`

### `{{memoriesRaw::[count]}}`
- **Purpose:** Raw memory chunks joined by separator, without header wrapper.
- **Args:** [count] — Override number of chunks to include
- **Usage:** `{{memoriesRaw::[count]}}`

### `{{memorySalience}}`
- **Purpose:** The highest narrative-importance memory from the current retrieval set.
- **Usage:** `{{memorySalience}}`

### `{{relationships}}`
- **Purpose:** Active relationship edges between entities in the current scene.
- **Usage:** `{{relationships}}`

## Multiplayer

### `{{currentPlayer}}`
- **Aliases:** `{{current_player}}`, `{{currentTurn}}`, `{{current_turn}}`
- **Purpose:** Name of the player whose turn it is (round-robin rooms). Empty in freeform rooms or outside a room.
- **Returns:** string
- **Usage:** `{{currentPlayer}}`

### `{{hostName}}`
- **Aliases:** `{{host_name}}`
- **Purpose:** Display name of the room's host. Empty outside a room.
- **Returns:** string
- **Usage:** `{{hostName}}`

### `{{isMultiplayer}}`
- **Aliases:** `{{is_multiplayer}}`, `{{isMultiplayerRoom}}`, `{{is_multiplayer_room}}`
- **Purpose:** Whether the current chat is a multiplayer room — "yes" or "no". Usable as an {{if}} condition.
- **Returns:** boolean
- **Usage:** `{{isMultiplayer}}`

### `{{playerCount}}`
- **Aliases:** `{{player_count}}`, `{{playersCount}}`, `{{players_count}}`
- **Purpose:** Number of active players in the room (host + peers). 0 outside a room.
- **Returns:** integer
- **Usage:** `{{playerCount}}`

### `{{players}}`
- **Aliases:** `{{player_names}}`, `{{playerNames}}`
- **Purpose:** Comma-separated names of all active players (host first). Empty outside a room. Pairs with {{foreach}}.
- **Returns:** string
- **Usage:** `{{players}}`

## Names

### `{{char}}`
- **Aliases:** `{{charName}}`
- **Purpose:** Current character name
- **Returns:** The character's name
- **Usage:** `{{char}}`

### `{{charGroupFocused}}`
- **Aliases:** `{{charFocused}}`, `{{char_group_focused}}`
- **Purpose:** Name of the focused/target character in a group chat. Empty in non-group chats.
- **Returns:** string
- **Usage:** `{{charGroupFocused}}`

### `{{group}}`
- **Purpose:** Comma-separated list of group member names
- **Returns:** string
- **Usage:** `{{group}}`

### `{{groupCardMode}}`
- **Aliases:** `{{group_card_mode}}`
- **Purpose:** Card composition mode for the active chat.
- **Returns:** "solo" | "swap" | "merge" | "merge_ignore_muted"
- **Usage:** `{{groupCardMode}}`

### `{{groupLastSpeaker}}`
- **Aliases:** `{{group_last_speaker}}`
- **Purpose:** Name of the last non-user character who spoke. Empty if none or non-group chat.
- **Returns:** string
- **Usage:** `{{groupLastSpeaker}}`

### `{{groupMemberCount}}`
- **Aliases:** `{{group_member_count}}`
- **Purpose:** Number of characters in the group chat. "0" in non-group chats.
- **Returns:** string
- **Usage:** `{{groupMemberCount}}`

### `{{groupNotMuted}}`
- **Aliases:** `{{group_not_muted}}`
- **Purpose:** Comma-separated list of non-muted group member names
- **Returns:** string
- **Usage:** `{{groupNotMuted}}`

### `{{groupOthers}}`
- **Aliases:** `{{group_others}}`
- **Purpose:** Comma-separated group member names excluding the focused character. Empty in non-group chats.
- **Returns:** string
- **Usage:** `{{groupOthers}}`

### `{{isGroupChat}}`
- **Aliases:** `{{is_group_chat}}`
- **Purpose:** Whether the current chat is a group chat
- **Returns:** "yes" or "no"
- **Usage:** `{{isGroupChat}}`

### `{{isNarrator}}`
- **Aliases:** `{{is_narrator}}`
- **Purpose:** Whether the active persona is a narrator (not a self-insert)
- **Returns:** "yes" or "no"
- **Usage:** `{{isNarrator}}`

### `{{notChar}}`
- **Aliases:** `{{not_char}}`
- **Purpose:** Name of the not-character (usually the user)
- **Returns:** string
- **Usage:** `{{notChar}}`

### `{{user}}`
- **Purpose:** Current user/persona name
- **Returns:** The user's display name
- **Usage:** `{{user}}`

## Random

### `{{pick::item1::item2}}`
- **Purpose:** Pick a random item from a list of arguments. Stable per evaluation when seeded.
- **Returns:** string
- **Usage:** `{{pick::item1::item2}}`

### `{{random::item1::item2}}`
- **Purpose:** Random integer between min and max (inclusive), or pick a random item from a list of strings
- **Args:** min_or_item1 — Minimum value or first item; max_or_item2 — Maximum value or second item
- **Returns:** string
- **Usage:** `{{random::item1::item2}}`

### `{{roll::dice}}`
- **Purpose:** Roll dice in NdS format (e.g., 2d6). Returns total.
- **Args:** dice — Dice notation like 2d6, 1d20, 3d8
- **Returns:** integer
- **Usage:** `{{roll::dice}}`

## Reasoning

### `{{reasoningPrefix::mode}}`
- **Purpose:** Reasoning/CoT opening tag from user settings. Pass 'raw' arg to strip newlines.
- **Args:** mode — Optional: 'raw' to strip surrounding newlines
- **Returns:** string
- **Usage:** `{{reasoningPrefix::mode}}`

### `{{reasoningSuffix::mode}}`
- **Purpose:** Reasoning/CoT closing tag from user settings. Pass 'raw' arg to strip newlines.
- **Args:** mode — Optional: 'raw' to strip surrounding newlines
- **Returns:** string
- **Usage:** `{{reasoningSuffix::mode}}`

## Regex

### `{{regexInstalled::scriptId::[text]}}`
- **Aliases:** `{{regex_installed::scriptId::[text]}}`, `{{hasRegex::scriptId::[text]}}`, `{{has_regex::scriptId::[text]}}`
- **Purpose:** Check if a regex script is installed, or apply it to text. Without text arg: returns 'true'/'false'. With text arg: applies the regex and returns the result.
- **Args:** scriptId — The script_id of the regex script; [text] — Text to apply the regex to (or use scoped body)
- **Returns:** string
- **Usage:** `{{regexInstalled::scriptId::[text]}}`

## State

### `{{hasExtension::name}}`
- **Aliases:** `{{has_extension::name}}`
- **Purpose:** Check if a named extension is active (returns 'true' or 'false')
- **Args:** name — Extension name
- **Returns:** boolean
- **Usage:** `{{hasExtension::name}}`

### `{{hasVar::name}}`
- **Aliases:** `{{hasPromptVar::name}}`, `{{hasPresetVar::name}}`
- **Purpose:** Returns 'true' if the named prompt variable is resolvable (runtime, schema, or default), 'false' otherwise.
- **Args:** name — Variable name
- **Usage:** `{{hasVar::name}}`

### `{{isMobile}}`
- **Aliases:** `{{is_mobile}}`
- **Purpose:** Whether the client is a mobile device
- **Returns:** boolean
- **Usage:** `{{isMobile}}`

### `{{lastGenerationType}}`
- **Aliases:** `{{last_generation_type}}`
- **Purpose:** Type of the last generation (normal, continue, regenerate, etc.)
- **Returns:** string
- **Usage:** `{{lastGenerationType}}`

### `{{maxContext}}`
- **Aliases:** `{{maxContextTokens}}`, `{{max_context}}`
- **Purpose:** Maximum context window tokens
- **Returns:** integer
- **Usage:** `{{maxContext}}`

### `{{maxPrompt}}`
- **Aliases:** `{{maxPromptTokens}}`, `{{max_prompt}}`
- **Purpose:** Maximum prompt tokens
- **Returns:** integer
- **Usage:** `{{maxPrompt}}`

### `{{maxResponse}}`
- **Aliases:** `{{maxResponseTokens}}`, `{{max_response}}`
- **Purpose:** Maximum response tokens
- **Returns:** integer
- **Usage:** `{{maxResponse}}`

### `{{model}}`
- **Purpose:** Current LLM model name
- **Returns:** string
- **Usage:** `{{model}}`

### `{{presetBlock::key}}`
- **Aliases:** `{{pblock::key}}`
- **Purpose:** Resolve a Lumiverse preset runtime block
- **Args:** key — Sealed block key
- **Returns:** string
- **Usage:** `{{presetBlock::key}}`

### `{{userColorMode}}`
- **Aliases:** `{{user_color_mode}}`, `{{colorMode}}`, `{{color_mode}}`
- **Purpose:** User's selected color scheme (dark, light, or system)
- **Returns:** string
- **Usage:** `{{userColorMode}}`

### `{{userInput}}`
- **Aliases:** `{{user_input}}`
- **Purpose:** Exact draft text from the input bar when this generation started
- **Returns:** string
- **Usage:** `{{userInput}}`

### `{{var::name::[op]::[keys]}}`
- **Aliases:** `{{promptVar::name::[op]::[keys]}}`, `{{presetVar::name::[op]::[keys]}}`
- **Purpose:** Read a preset-scoped prompt variable value. Returns the runtime value (including any {{setvar::}} overrides), then the end-user configured value, then the creator default, then an empty string. With sub-syntax {{var::name::ison::key1,key2,…}}, returns 'true' iff every listed multiselect option key is currently selected.
- **Args:** name — Variable name defined on a prompt block; [op] — Optional sub-operation. Currently only 'ison' is supported (multiselect).; [keys] — Comma-separated option keys for 'ison' (AND-matched).
- **Usage:** `{{var::name::[op]::[keys]}}`

### `{{varDefault::name}}`
- **Aliases:** `{{promptVarDefault::name}}`, `{{presetVarDefault::name}}`
- **Purpose:** Read the creator-declared default for a prompt variable, ignoring any end-user override.
- **Args:** name — Variable name
- **Usage:** `{{varDefault::name}}`

## String

### `{{capitalize::text}}`
- **Aliases:** `{{titlecase::text}}`
- **Purpose:** Capitalize the first letter of each sentence
- **Args:** text — Text to capitalize
- **Returns:** string
- **Usage:** `{{capitalize::text}}`

### `{{join::item1::item2}}`
- **Purpose:** Join multiple values with a separator
- **Args:** separator — Separator string; items — Values to join
- **Returns:** string
- **Usage:** `{{join::item1::item2}}`

### `{{len::text}}`
- **Aliases:** `{{length::text}}`
- **Purpose:** Length of a string (character count)
- **Args:** text — Text to measure
- **Returns:** integer
- **Usage:** `{{len::text}}`

### `{{lower::text}}`
- **Aliases:** `{{lowercase::text}}`, `{{toLower::text}}`
- **Purpose:** Convert text to lowercase
- **Args:** text — Text to convert
- **Returns:** string
- **Usage:** `{{lower::text}}`

### `{{regex::pattern::replacement::[text]::[flags]}}`
- **Purpose:** Regex replacement. {{regex::pattern::replacement::text}} or scoped.
- **Args:** pattern — Regular expression pattern; replacement — Replacement string ($1, $2 for groups); [text] — Source text (or use scoped body); [flags] — Regex flags (default: g)
- **Returns:** string
- **Usage:** `{{regex::pattern::replacement::[text]::[flags]}}`

### `{{repeat::count::[text]}}`
- **Purpose:** Repeat text N times. Scoped: {{repeat::3}}text{{/repeat}}
- **Args:** count — Number of repetitions; [text] — Text to repeat (or use scoped body)
- **Returns:** string
- **Usage:** `{{repeat::count::[text]}}`

### `{{replace::find::with::[text]}}`
- **Purpose:** Replace occurrences of a substring. Scoped: {{replace::find::with}}text{{/replace}}
- **Args:** find — String to find; with — Replacement string; [text] — Source text (or use scoped body)
- **Returns:** string
- **Usage:** `{{replace::find::with::[text]}}`

### `{{split::text::delimiter::index}}`
- **Purpose:** Split text by delimiter and return the Nth item (0-based)
- **Args:** text — Text to split; delimiter — Delimiter string; index — Item index (0-based)
- **Returns:** string
- **Usage:** `{{split::text::delimiter::index}}`

### `{{substr::text::start::[end]}}`
- **Aliases:** `{{substring::text::start::[end]}}`
- **Purpose:** Extract a substring by start and optional end index
- **Args:** text — Source text; start — Start index (0-based); [end] — End index (exclusive)
- **Returns:** string
- **Usage:** `{{substr::text::start::[end]}}`

### `{{tokenCount::text}}`
- **Aliases:** `{{token_count::text}}`, `{{tokens::text}}`
- **Purpose:** Approximate token count of text (~4 chars per token)
- **Args:** text — Text to estimate
- **Returns:** integer
- **Usage:** `{{tokenCount::text}}`

### `{{truncate::text::maxTokens}}`
- **Purpose:** Truncate text to approximately N tokens (word-boundary aware)
- **Args:** text — Text to truncate; maxTokens — Maximum token count
- **Returns:** string
- **Usage:** `{{truncate::text::maxTokens}}`

### `{{upper::text}}`
- **Aliases:** `{{uppercase::text}}`, `{{toUpper::text}}`
- **Purpose:** Convert text to uppercase
- **Args:** text — Text to convert
- **Returns:** string
- **Usage:** `{{upper::text}}`

### `{{wrap::prefix::suffix::[text]}}`
- **Purpose:** Wrap text with prefix and suffix. Only wraps if text is non-empty.
- **Args:** prefix — Prefix string; suffix — Suffix string; [text] — Text to wrap (or use scoped body)
- **Returns:** string
- **Usage:** `{{wrap::prefix::suffix::[text]}}`

## Time

### `{{date}}`
- **Purpose:** Current date (Month Day, Year)
- **Returns:** string
- **Usage:** `{{date}}`

### `{{datetimeformat::[format]}}`
- **Purpose:** Format current date/time with a custom Intl pattern
- **Args:** [format] — Intl.DateTimeFormat options as key=value pairs
- **Returns:** string
- **Usage:** `{{datetimeformat::[format]}}`

### `{{idleDuration}}`
- **Aliases:** `{{idle_duration}}`
- **Purpose:** Human-readable time since last message
- **Returns:** string
- **Usage:** `{{idleDuration}}`

### `{{isodate}}`
- **Purpose:** Current date in ISO format (YYYY-MM-DD)
- **Returns:** string
- **Usage:** `{{isodate}}`

### `{{isotime}}`
- **Purpose:** Current date and time in ISO 8601 format
- **Returns:** string
- **Usage:** `{{isotime}}`

### `{{time::[utcOffset]}}`
- **Purpose:** Current time (HH:MM). Accepts optional UTC offset argument.
- **Args:** [utcOffset] — UTC offset like UTC+2 or UTC-5
- **Returns:** string
- **Usage:** `{{time::[utcOffset]}}`

### `{{timeDiff::date1::[date2]}}`
- **Aliases:** `{{time_diff::date1::[date2]}}`
- **Purpose:** Human-readable difference between two ISO date strings
- **Args:** date1 — First ISO date string; [date2] — Second ISO date string (defaults to now)
- **Returns:** string
- **Usage:** `{{timeDiff::date1::[date2]}}`

### `{{weekday}}`
- **Purpose:** Current day of the week
- **Returns:** string
- **Usage:** `{{weekday}}`

## Variables

### `{{addchatvar::key::value}}`
- **Purpose:** Add a numeric value to a chat-scoped persisted variable
- **Args:** key — Variable name; value — Number to add
- **Returns:** number
- **Usage:** `{{addchatvar::key::value}}`

### `{{addgvar::key::value}}`
- **Aliases:** `{{addglobalvar::key::value}}`
- **Purpose:** Add a numeric value to a global variable
- **Args:** key — Variable name; value — Number to add
- **Returns:** number
- **Usage:** `{{addgvar::key::value}}`

### `{{addvar::key::value}}`
- **Purpose:** Add a numeric value to a local variable
- **Args:** key — Variable name; value — Number to add
- **Returns:** number
- **Usage:** `{{addvar::key::value}}`

### `{{decchatvar::key}}`
- **Purpose:** Decrement a chat-scoped persisted variable by 1
- **Args:** key — Variable name
- **Returns:** integer
- **Usage:** `{{decchatvar::key}}`

### `{{decgvar::key}}`
- **Aliases:** `{{decglobalvar::key}}`
- **Purpose:** Decrement a global variable by 1
- **Args:** key — Variable name
- **Returns:** integer
- **Usage:** `{{decgvar::key}}`

### `{{decvar::key}}`
- **Purpose:** Decrement a local variable by 1
- **Args:** key — Variable name
- **Returns:** integer
- **Usage:** `{{decvar::key}}`

### `{{deletechatvar::key}}`
- **Aliases:** `{{flushchatvar::key}}`
- **Purpose:** Delete a chat-scoped persisted variable
- **Args:** key — Variable name
- **Returns:** string
- **Usage:** `{{deletechatvar::key}}`

### `{{deletegvar::key}}`
- **Aliases:** `{{flushgvar::key}}`, `{{flushglobalvar::key}}`, `{{deleteglobalvar::key}}`
- **Purpose:** Delete a global variable
- **Args:** key — Variable name
- **Returns:** string
- **Usage:** `{{deletegvar::key}}`

### `{{deletevar::key}}`
- **Aliases:** `{{flushvar::key}}`
- **Purpose:** Delete a local variable
- **Args:** key — Variable name
- **Returns:** string
- **Usage:** `{{deletevar::key}}`

### `{{getchatvar::key}}`
- **Purpose:** Get a chat-scoped persisted variable value
- **Args:** key — Variable name
- **Returns:** string
- **Usage:** `{{getchatvar::key}}`

### `{{getgvar::key}}`
- **Aliases:** `{{getglobalvar::key}}`
- **Purpose:** Get a global variable value
- **Args:** key — Variable name
- **Returns:** string
- **Usage:** `{{getgvar::key}}`

### `{{getvar::key}}`
- **Purpose:** Get a local (chat-scoped) variable value
- **Args:** key — Variable name
- **Returns:** string
- **Usage:** `{{getvar::key}}`

### `{{haschatvar::key}}`
- **Purpose:** Check if a chat-scoped persisted variable exists (returns 'true' or 'false')
- **Args:** key — Variable name
- **Returns:** boolean
- **Usage:** `{{haschatvar::key}}`

### `{{hasgvar::key}}`
- **Aliases:** `{{hasglobalvar::key}}`, `{{gvarexists::key}}`
- **Purpose:** Check if a global variable exists (returns 'true' or 'false')
- **Args:** key — Variable name
- **Returns:** boolean
- **Usage:** `{{hasgvar::key}}`

### `{{incchatvar::key}}`
- **Purpose:** Increment a chat-scoped persisted variable by 1
- **Args:** key — Variable name
- **Returns:** integer
- **Usage:** `{{incchatvar::key}}`

### `{{incgvar::key}}`
- **Aliases:** `{{incglobalvar::key}}`
- **Purpose:** Increment a global variable by 1
- **Args:** key — Variable name
- **Returns:** integer
- **Usage:** `{{incgvar::key}}`

### `{{incvar::key}}`
- **Purpose:** Increment a local variable by 1
- **Args:** key — Variable name
- **Returns:** integer
- **Usage:** `{{incvar::key}}`

### `{{let}}`
- **Aliases:** `{{withVar}}`, `{{scope}}`
- **Purpose:** Temporarily bind local variables for a scoped body, then restore previous values.
- **Returns:** string
- **Usage:** `{{let}}`

### `{{setchatvar::key::value}}`
- **Purpose:** Set a chat-scoped persisted variable (persists across generations)
- **Args:** key — Variable name; value — Value to set
- **Returns:** string
- **Usage:** `{{setchatvar::key::value}}`

### `{{setgvar::key::value}}`
- **Aliases:** `{{setglobalvar::key::value}}`
- **Purpose:** Set a global variable
- **Args:** key — Variable name; value — Value to set
- **Returns:** string
- **Usage:** `{{setgvar::key::value}}`

### `{{setvar::key::value}}`
- **Purpose:** Set a local variable (returns empty string)
- **Args:** key — Variable name; value — Value to set
- **Returns:** string
- **Usage:** `{{setvar::key::value}}`

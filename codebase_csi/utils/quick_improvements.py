"""
Quick improvement implementations for CodebaseCSI.
These are "low-hanging fruit" improvements that provide immediate value.
"""

from typing import List, Dict
from pathlib import Path


class ProgressReporter:
    """Progress reporting for better UX."""
    
    def __init__(self, total_files: int, use_tqdm: bool = True):
        """
        Initialize progress reporter.
        
        Args:
            total_files: Total number of files to process
            use_tqdm: Whether to use tqdm (if available)
        """
        self.total_files = total_files
        self.processed = 0
        self.use_tqdm = use_tqdm
        self.pbar = None
        
        if use_tqdm:
            try:
                from tqdm import tqdm
                self.pbar = tqdm(total=total_files, desc="Scanning files", unit="file")
            except ImportError:
                self.use_tqdm = False
    
    def update(self, file_path: str, confidence: float):
        """Update progress with current file."""
        self.processed += 1
        
        if self.pbar:
            self.pbar.set_postfix({
                'file': Path(file_path).name[:20],
                'confidence': f'{confidence:.2%}'
            })
            self.pbar.update(1)
        else:
            # Fallback: simple print
            print(f"[{self.processed}/{self.total_files}] {Path(file_path).name}: {confidence:.2%}")
    
    def close(self):
        """Close progress reporter."""
        if self.pbar:
            self.pbar.close()


class ExplainMode:
    """Explain why each file was flagged."""
    
    @staticmethod
    def explain_result(file_analysis) -> str:
        """
        Generate human-readable explanation for detection result.
        
        Args:
            file_analysis: FileAnalysis object
            
        Returns:
            Detailed explanation string
        """
        lines = []
        lines.append(f"\n{'='*80}")
        lines.append(f"📄 File: {file_analysis.file_path}")
        lines.append(f"{'='*80}")
        lines.append(f"\n🎯 Overall Confidence: {file_analysis.confidence_score:.2%} ({file_analysis.confidence_level.value})")
        
        if not file_analysis.is_ai_generated:
            lines.append("\n✅ This file appears to be human-written.")
            return '\n'.join(lines)
        
        lines.append(f"\n⚠️  This file shows signs of AI generation:")
        
        # Group patterns by type
        from collections import defaultdict
        patterns_by_type = defaultdict(list)
        
        for pattern in file_analysis.patterns:
            patterns_by_type[pattern.get('type', 'unknown')].append(pattern)
        
        # Explain each pattern type
        for pattern_type, patterns in sorted(patterns_by_type.items()):
            count = len(patterns)
            lines.append(f"\n  {ExplainMode._get_pattern_emoji(pattern_type)} {pattern_type.replace('_', ' ').title()} ({count} occurrences)")
            
            # Show top 3 examples
            for pattern in patterns[:3]:
                line_num = pattern.get('line', 0)
                confidence = pattern.get('confidence', 0)
                lines.append(f"    • Line {line_num}: {confidence:.0%} confidence")
                
                if 'context' in pattern:
                    context = pattern['context'][:60]
                    lines.append(f"      Context: {context}...")
        
        # Add recommendations
        lines.append(f"\n💡 Recommendations:")
        recommendations = ExplainMode._get_recommendations(file_analysis)
        for i, rec in enumerate(recommendations, 1):
            lines.append(f"  {i}. {rec}")
        
        return '\n'.join(lines)
    
    @staticmethod
    def _get_pattern_emoji(pattern_type: str) -> str:
        """Get emoji for pattern type."""
        emoji_map = {
            'emoji': '😀',
            'generic_naming': '🏷️',
            'verbose_comments': '💬',
            'sql_injection': '🔒',
            'command_injection': '⚠️',
            'magic_numbers': '🔢',
            'god_function': '👹',
            'cyclomatic_complexity': '🔀',
            'token_diversity': '📊',
        }
        return emoji_map.get(pattern_type, '❓')
    
    @staticmethod
    def _get_recommendations(file_analysis) -> List[str]:
        """Get actionable recommendations."""
        recommendations = []
        
        # Analyze patterns and provide specific advice
        pattern_types = {p.get('type') for p in file_analysis.patterns}
        
        if 'emoji' in pattern_types:
            recommendations.append("Remove all emojis from code and comments")
        
        if 'generic_naming' in pattern_types:
            recommendations.append("Replace generic variable names (temp, data, result) with descriptive names")
        
        if 'verbose_comments' in pattern_types:
            recommendations.append("Reduce comment verbosity - explain WHY, not WHAT")
        
        if any('sql' in pt for pt in pattern_types if pt):
            recommendations.append("Use parameterized queries to prevent SQL injection")
        
        if 'god_function' in pattern_types or 'cyclomatic_complexity' in pattern_types:
            recommendations.append("Break large functions into smaller, focused methods")
        
        if not recommendations:
            recommendations.append("Review flagged sections and apply general refactoring best practices")
        
        return recommendations


class QuickMode:
    """Quick scan mode - only check high-confidence patterns."""
    
    QUICK_ANALYZERS = ['emoji', 'security']  # Fast and high-confidence
    
    @staticmethod
    def get_quick_analyzers():
        """Get list of analyzers for quick mode."""
        return QuickMode.QUICK_ANALYZERS


class ColorCoding:
    """Color-coded confidence levels for terminal output."""
    
    # ANSI color codes
    RED = '\033[91m'
    YELLOW = '\033[93m'
    GREEN = '\033[92m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    RESET = '\033[0m'
    
    @staticmethod
    def colorize_confidence(confidence: float) -> str:
        """
        Return color-coded confidence string.
        
        Args:
            confidence: Confidence score (0.0-1.0)
            
        Returns:
            Color-coded string
        """
        if confidence >= 0.7:
            color = ColorCoding.RED
            emoji = '🔴'
            level = 'HIGH RISK'
        elif confidence >= 0.4:
            color = ColorCoding.YELLOW
            emoji = '🟡'
            level = 'MEDIUM RISK'
        else:
            color = ColorCoding.GREEN
            emoji = '🟢'
            level = 'LOW RISK'
        
        return f"{color}{ColorCoding.BOLD}{emoji} {confidence:.0%} - {level}{ColorCoding.RESET}"
    
    @staticmethod
    def format_file_result(file_path: str, confidence: float, max_path_len: int = 50) -> str:
        """
        Format file scan result with colors.
        
        Args:
            file_path: Path to file
            confidence: Confidence score
            max_path_len: Maximum path length to display
            
        Returns:
            Formatted string
        """
        # Truncate path if needed
        display_path = str(file_path)
        if len(display_path) > max_path_len:
            display_path = '...' + display_path[-(max_path_len-3):]
        
        # Pad path for alignment
        padded_path = display_path.ljust(max_path_len)
        
        # Color-coded confidence
        colored_confidence = ColorCoding.colorize_confidence(confidence)
        
        return f"{padded_path}  {colored_confidence}"


class AutoFix:
    """Automatic remediation for simple issues."""
    
    @staticmethod
    def remove_emojis(content: str) -> str:
        """
        Remove all emojis from content.
        
        Args:
            content: File content
            
        Returns:
            Content with emojis removed
        """
        import re
        
        # Unicode ranges for emojis (same as EmojiDetector)
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # Emoticons
            "\U0001F300-\U0001F5FF"  # Symbols & Pictographs
            "\U0001F680-\U0001F6FF"  # Transport & Map
            "\U0001F1E0-\U0001F1FF"  # Flags
            "\U00002702-\U000027B0"  # Dingbats
            "\U000024C2-\U0001F251"
            "\U0001F900-\U0001F9FF"  # Supplemental
            "\U0001FA70-\U0001FAFF"  # Extended
            "\U00002600-\U000026FF"  # Misc Symbols
            "\U00002700-\U000027BF"
            "]+",
            flags=re.UNICODE
        )
        
        return emoji_pattern.sub('', content)
    
    @staticmethod
    def fix_generic_naming(content: str, replacements: Dict[str, str]) -> str:
        """
        Replace generic variable names with descriptive ones.
        
        Args:
            content: File content
            replacements: Dict mapping generic names to descriptive ones
            
        Returns:
            Content with improved naming
        """
        import re
        
        for generic, descriptive in replacements.items():
            # Use word boundaries to avoid partial matches
            pattern = r'\b' + re.escape(generic) + r'\b'
            content = re.sub(pattern, descriptive, content)
        
        return content
    
    @staticmethod
    def apply_fixes(file_path: Path, file_analysis, dry_run: bool = True) -> Dict:
        """
        Apply automatic fixes to file.
        
        Args:
            file_path: Path to file
            file_analysis: FileAnalysis object
            dry_run: If True, don't actually modify file
            
        Returns:
            Dict with fix results
        """
        results = {
            'file': str(file_path),
            'fixes_applied': [],
            'dry_run': dry_run,
        }
        
        # Read file
        content = file_path.read_text(encoding='utf-8')
        modified_content = content
        
        # Check for emoji patterns
        emoji_patterns = [p for p in file_analysis.patterns if p.get('type') == 'emoji']
        if emoji_patterns:
            modified_content = AutoFix.remove_emojis(modified_content)
            results['fixes_applied'].append({
                'type': 'emoji_removal',
                'count': len(emoji_patterns),
                'description': f"Removed {len(emoji_patterns)} emojis"
            })
        
        # Check if any fixes were applied
        if modified_content != content:
            if not dry_run:
                # Write back to file
                file_path.write_text(modified_content, encoding='utf-8')
                results['status'] = 'modified'
            else:
                results['status'] = 'would_modify'
        else:
            results['status'] = 'no_changes'
        
        return results


# Example usage functions
def example_progress():
    """Example: Using progress reporter."""
    files = [f"file{i}.py" for i in range(100)]
    reporter = ProgressReporter(len(files))
    
    for file in files:
        # Simulate scanning
        confidence = 0.5
        reporter.update(file, confidence)
    
    reporter.close()


def example_explain():
    """Example: Using explain mode."""
    from codebase_csi.core.models import FileAnalysis, ConfidenceLevel, DetectionPattern
    
    # Create sample analysis
    analysis = FileAnalysis(
        file_path="example.py",
        language="python",
        lines_of_code=100,
        confidence_score=0.75,
        confidence_level=ConfidenceLevel.HIGH,
        patterns=[
            DetectionPattern(
                pattern_type="emoji",
                description="Emoji in comment",
                line_number=5,
                code_snippet="# Task complete ✅",
                confidence=0.9,
                severity="medium"
            )
        ]
    )
    
    explanation = ExplainMode.explain_result(analysis)
    print(explanation)


def example_color_coding():
    """Example: Using color coding."""
    print("\nConfidence Level Color Coding:")
    print(ColorCoding.format_file_result("path/to/file1.py", 0.85))
    print(ColorCoding.format_file_result("path/to/file2.py", 0.55))
    print(ColorCoding.format_file_result("path/to/file3.py", 0.25))


if __name__ == '__main__':
    print("Quick Improvements Demo")
    print("="*80)
    example_color_coding()

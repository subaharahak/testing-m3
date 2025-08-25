# gen.py
import random
import re

class CardGenerator:
    """
    A class to generate valid credit card numbers based on a given BIN pattern
    using the Luhn algorithm.
    """
    def __init__(self):
        # Regex pattern to validate the user's input (only digits, 'x', and '|')
        self.bin_pattern = re.compile(r'^[0-9xX|]+$')

    def luhn_checksum(self, card_number):
        """
        Calculates the Luhn checksum for a given string of digits.
        Returns the check digit needed to make the number valid.
        """
        def digits_of(n):
            return [int(d) for d in str(n)]
        
        # Reverse the digits and split into odd & even indices
        digits = digits_of(card_number)
        odd_digits = digits[-1::-2]    # digits at odd positions (1-indexed)
        even_digits = digits[-2::-2]   # digits at even positions (1-indexed)
        
        checksum = sum(odd_digits)
        for d in even_digits:
            checksum += sum(digits_of(d * 2))
            
        return (checksum % 10)

    def calculate_check_digit(self, partial_number):
        """
        Given a partial number (without the last check digit),
        calculates the valid Luhn check digit and returns it.
        """
        # Calculate the checksum for partial_number + '0'
        checksum = self.luhn_checksum(partial_number + '0')
        # The check digit is the amount needed to reach a multiple of 10
        return (10 - checksum) % 10

    def generate_valid_card(self, pattern, mm=None, yy=None, cvv=None):
        """
        Generates a single valid card number from a pattern.
        Pattern example: '439383xxxxxx'
        """
        # Count how many 'x' characters we need to replace
        x_count = pattern.count('x') + pattern.count('X')
        
        # If there are no 'x' characters, we need to generate the check digit
        if x_count == 0:
            # Remove the last digit (current check digit) and calculate a new one
            partial_number = pattern[:-1]
            check_digit = self.calculate_check_digit(partial_number)
            return partial_number + str(check_digit)
        
        # Generate random digits for each 'x'
        random_digits = ''.join(str(random.randint(0, 9)) for _ in range(x_count))
        
        # Build the card number by replacing each 'x' with a random digit
        card_without_check = []
        digit_index = 0
        for char in pattern:
            if char in 'xX':
                card_without_check.append(random_digits[digit_index])
                digit_index += 1
            else:
                card_without_check.append(char)
                
        card_without_check_str = ''.join(card_without_check)
        
        # Calculate the final check digit using the Luhn algorithm
        check_digit = self.calculate_check_digit(card_without_check_str)
        
        # Return the complete, valid card number
        return card_without_check_str + str(check_digit)

    def parse_input_pattern(self, input_pattern):
        """
        Parse different input formats and return a standardized pattern
        """
        # Remove any spaces
        input_pattern = input_pattern.replace(' ', '')
        
        # Case 1: Just a BIN (6+ digits)
        if re.match(r'^\d{6,}$', input_pattern) and '|' not in input_pattern:
            bin_part = input_pattern[:6]  # Take first 6 digits as BIN
            remaining_length = 16 - len(bin_part) - 1  # -1 for check digit
            if remaining_length > 0:
                return bin_part + 'x' * remaining_length
            else:
                return bin_part  # If already 16 digits, just return it
        
        # Case 2: BIN|MM|YY|CVV format
        elif '|' in input_pattern:
            parts = input_pattern.split('|')
            if len(parts) >= 4:
                # This is a full card format, we'll handle the generation differently
                return input_pattern
            else:
                # Partial format, treat as pattern
                return input_pattern.replace('|', '')
        
        # Case 3: Pattern with x's
        else:
            return input_pattern

    def generate_from_pattern(self, pattern, amount=10):
        """
        Generate cards based on different pattern types
        """
        # Check if it's a BIN|MM|YY|CVV format
        if '|' in pattern and pattern.count('|') >= 3:
            parts = pattern.split('|')
            if len(parts[0]) >= 6:  # At least BIN is provided
                bin_part = parts[0]
                mm = parts[1] if len(parts) > 1 else str(random.randint(1, 12)).zfill(2)
                yy = parts[2] if len(parts) > 2 else str(random.randint(23, 33)).zfill(2)
                cvv = parts[3] if len(parts) > 3 else str(random.randint(100, 999))
                
                # Generate cards with this format
                cards = []
                for _ in range(amount):
                    # Generate card number from BIN
                    card_number = self.generate_valid_card(bin_part + 'x' * (16 - len(bin_part)), mm, yy, cvv)
                    cards.append(f"{card_number}|{mm}|{yy}|{cvv}")
                return cards
        
        # Regular pattern generation (with x's)
        cards = []
        for _ in range(amount):
            card_number = self.generate_valid_card(pattern)
            # If it's just a card number, add random MM/YY/CVV
            if '|' not in pattern and len(pattern) >= 6:
                mm = str(random.randint(1, 12)).zfill(2)
                yy = str(random.randint(23, 33)).zfill(2)
                cvv = str(random.randint(100, 999))
                cards.append(f"{card_number}|{mm}|{yy}|{cvv}")
            else:
                cards.append(card_number)
        return cards

    def validate_pattern(self, pattern):
        """
        Validates the user's input pattern.
        Returns (True, cleaned_pattern) if valid, or (False, error_message) if invalid.
        """
        # Remove any spaces the user might have entered
        pattern = pattern.replace(' ', '')
        
        # Check if the pattern contains only numbers, 'x', and '|'
        if not self.bin_pattern.match(pattern):
            return False, "❌ Invalid pattern. Please use only digits (0-9), 'x', and '|' characters. Example: `/gen 439383xxxxxx` or `/gen 483318|12|25|123`"
        
        # Check if it's a BIN|MM|YY|CVV format
        if '|' in pattern:
            parts = pattern.split('|')
            if len(parts[0]) < 6:
                return False, "❌ BIN must be at least 6 digits. Example: `/gen 483318|12|25|123`"
        else:
            # Check if the pattern has at least 6 digits to work with
            digit_count = len(re.findall(r'\d', pattern))
            if digit_count < 6:
                return False, "❌ Pattern must contain at least 6 digits. Example: `/gen 483318` or `/gen 483318xxxxxx`"
        
        # Basic length check for patterns without pipes
        if '|' not in pattern and (len(pattern) < 6 or len(pattern) > 19):
            return False, "❌ Invalid length. Card numbers are typically between 6-19 digits."
            
        return True, pattern

    def generate_cards(self, input_pattern, amount=10):
        """
        The main function to be called from the bot.
        Generates 'amount' of valid card numbers based on the pattern.
        Returns a list of cards and an optional error message.
        """
        # Validate the pattern first
        is_valid, result = self.validate_pattern(input_pattern)
        if not is_valid:
            return [], result  # result contains the error message
        
        # Parse the input pattern to standardized format
        parsed_pattern = self.parse_input_pattern(result)
        
        generated_cards = []
        
        # Generate the requested amount of cards
        for _ in range(amount):
            try:
                cards = self.generate_from_pattern(parsed_pattern, 1)
                generated_cards.extend(cards)
            except Exception as e:
                # Catch any unexpected errors during generation
                return [], f"❌ An error occurred during generation: {str(e)}"
                
        # Return the list of cards and no error (None)
        return generated_cards, None


# Example usage and testing if this file is run directly
if __name__ == "__main__":
    print("Testing the CardGenerator module...\n")
    
    generator = CardGenerator()
    
    # Test different patterns
    test_patterns = [
        "483318",  # Just BIN
        "483318|12|25|123",  # BIN with MM/YY/CVV
        "4729273826xxxx112133",  # Pattern with x's
        "4393830123456789",  # Complete card number
    ]
    
    for pattern in test_patterns:
        print(f"Testing pattern: {pattern}")
        cards, error = generator.generate_cards(pattern, 3)
        
        if error:
            print(f"Error: {error}")
        else:
            print("✅ Generated cards:")
            for i, card in enumerate(cards, 1):
                print(f"{i}. {card}")
        print()
